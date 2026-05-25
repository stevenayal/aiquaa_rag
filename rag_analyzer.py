"""
rag_analyzer.py — Analiza requerimientos y devuelve regulaciones aplicables.

Flujo:
  1. Recibe requerimiento/feature en texto libre
  2. Claude Haiku clasifica: industry + topics + search_query reformulada
  3. Voyage AI embeds search_query → vector
  4. pgvector busca chunks filtrados por industry + topics
  5. Claude Sonnet analiza qué regulaciones aplican al requerimiento

Uso:
  python rag_analyzer.py "El módulo debe permitir transferencias SIPAP entre cuentas"
  python rag_analyzer.py --interactive
  python rag_analyzer.py --industry banca --topics transferencias,riesgo "..."
"""

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

from dotenv import load_dotenv

_root = Path(__file__).parent
for _env in [_root / ".env", _root / "BCP" / ".env", _root / "CONATEL" / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_SERVICE_KEY"]
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]

VOYAGE_MODEL      = "voyage-3"
CLAUDE_CLASSIFIER = "claude-haiku-4-5"   # rápido/barato para clasificación
CLAUDE_ANALYZER   = "claude-sonnet-4-5"  # calidad para el análisis final

DEFAULT_TOP_K     = 10
DEFAULT_THRESHOLD = 0.38

# Taxonomía completa — se pasa al clasificador para que use los mismos valores
TOPICS_BANCA = [
    "transferencias", "atm", "tarjetas", "cuenta_corriente", "cuenta_basica",
    "capital", "cambios", "auditoria", "riesgo", "fraude_seguridad",
    "tecnologia", "firma_digital", "reporto", "tasas_interes", "tercerizacion",
    "credito_cartera", "depositos", "contabilidad", "liquidez", "aml",
    "gobierno_corporativo", "mercado_capitales", "seguros", "cheques",
    "disolucion_entidades", "asesoria_financiera", "seguro_depositos",
]
TOPICS_TELECOM = [
    "espectro", "concesiones", "internet", "telefonia", "radiodifusion",
    "tarifas", "interconexion",
]
ALL_TOPICS = TOPICS_BANCA + TOPICS_TELECOM


# ── Prompts ────────────────────────────────────────────────────────────────────

CLASSIFIER_SYSTEM = f"""Sos un experto en regulaciones financieras y de telecomunicaciones de Paraguay.
Tu tarea es analizar un requerimiento de software y determinar qué regulaciones aplican.

INDUSTRIAS disponibles:
- banca            → regulaciones BCP (Banco Central del Paraguay)
- telecomunicaciones → regulaciones CONATEL

TOPICS disponibles por industria:
banca: {', '.join(TOPICS_BANCA)}
telecomunicaciones: {', '.join(TOPICS_TELECOM)}

Devolvé SIEMPRE un JSON válido con esta estructura exacta:
{{
  "industry": "<banca|telecomunicaciones|ambas|ninguna>",
  "topics": ["<topic1>", "<topic2>"],
  "product_description": "<descripción breve del producto/módulo en 1 línea>",
  "search_query": "<consulta optimizada para búsqueda semántica en 1-2 oraciones>",
  "confidence": "<alta|media|baja>"
}}

Reglas:
- Usá SOLO topics de la lista. Si ninguno aplica, dejá topics=[].
- search_query debe ser específica y en español, enfocada en el aspecto regulatorio.
- Si es "ambas" industrias, listá topics de ambas.
- Si es "ninguna", igual intentá un search_query útil.
"""

ANALYZER_SYSTEM = """Sos un especialista en compliance y regulaciones de Paraguay (BCP y CONATEL).
Tu función es analizar un requerimiento de software e identificar qué regulaciones deben
contemplarse en el diseño y los casos de prueba.

Al responder:
1. Identificá las obligaciones regulatorias que aplican directamente al requerimiento.
2. Señalá los artículos, resoluciones o circulares específicas más relevantes.
3. Listá los aspectos concretos que los casos de prueba DEBEN verificar por cumplimiento.
4. Indicá si hay algún gap regulatorio (requerimiento no cubierto por las normas encontradas).
5. Citá siempre la fuente (título + URL) para cada punto.

Respondé en español. Sé preciso y accionable — el equipo QA usará esto para escribir test cases.
"""


# ── Clientes ───────────────────────────────────────────────────────────────────

def get_clients():
    import anthropic
    import voyageai
    from supabase import create_client
    sb     = create_client(SUPABASE_URL, SUPABASE_KEY)
    voyage = voyageai.Client(api_key=VOYAGE_API_KEY)
    claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    return sb, voyage, claude


# ── Paso 1: Clasificación ──────────────────────────────────────────────────────

@dataclass
class Classification:
    industry: str                  # banca | telecomunicaciones | ambas | ninguna
    topics: list[str]
    product_description: str
    search_query: str
    confidence: str


def classify_requirement(claude, requirement: str,
                          industry_override: Optional[str] = None,
                          topics_override: Optional[list[str]] = None) -> Classification:
    """Usa Claude Haiku para clasificar el requerimiento."""

    # Si el usuario pasó overrides, saltar el LLM
    if industry_override and topics_override:
        return Classification(
            industry=industry_override,
            topics=topics_override,
            product_description="(override manual)",
            search_query=requirement,
            confidence="alta",
        )

    log.info("Clasificando requerimiento...")
    response = claude.messages.create(
        model=CLAUDE_CLASSIFIER,
        max_tokens=512,
        system=CLASSIFIER_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Requerimiento a clasificar:\n\n{requirement}",
        }],
    )

    raw = response.content[0].text.strip()
    # Extraer JSON aunque venga con texto alrededor
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    data  = json.loads(raw[start:end])

    cls = Classification(
        industry=data.get("industry", "ninguna"),
        topics=[t for t in data.get("topics", []) if t in ALL_TOPICS],
        product_description=data.get("product_description", ""),
        search_query=data.get("search_query", requirement),
        confidence=data.get("confidence", "media"),
    )

    log.info(f"  industry={cls.industry} | topics={cls.topics} | conf={cls.confidence}")
    log.info(f"  producto: {cls.product_description}")
    log.info(f"  search_query: {cls.search_query}")
    return cls


# ── Paso 2: Búsqueda semántica filtrada ────────────────────────────────────────

def embed_query(voyage, text: str) -> list[float]:
    result = voyage.embed([text], model=VOYAGE_MODEL, input_type="query")
    return result.embeddings[0]


def search_regulations(sb, query_vec: list[float], cls: Classification,
                        top_k: int, threshold: float) -> list[dict]:
    """Búsqueda vectorial filtrada por industry + topics."""

    # Determinar filtros
    filter_industry = None
    filter_topics   = None

    if cls.industry in ("banca", "telecomunicaciones"):
        filter_industry = cls.industry
    # "ambas" → sin filtro de industria (busca en todo el corpus)

    if cls.topics:
        filter_topics = cls.topics

    params = {
        "query_embedding": query_vec,
        "match_count":     top_k,
        "match_threshold": threshold,
    }
    if filter_industry:
        params["filter_industry"] = filter_industry
    if filter_topics:
        params["filter_topics"] = filter_topics

    log.info(f"Buscando chunks (industry={filter_industry}, topics={filter_topics}, top_k={top_k})...")
    try:
        res = sb.rpc("match_rag_chunks_v2", params).execute()
        chunks = res.data or []
    except Exception as e:
        log.error(f"Error búsqueda vectorial: {e}")
        chunks = []

    # Si con topics no hay resultados suficientes, ampliar sin topics
    if len(chunks) < 3 and filter_topics:
        log.info(f"  Solo {len(chunks)} resultados con topics, ampliando sin filtro de topics...")
        params_wide = {k: v for k, v in params.items() if k != "filter_topics"}
        try:
            res2 = sb.rpc("match_rag_chunks_v2", params_wide).execute()
            chunks = res2.data or []
        except Exception:
            pass

    log.info(f"  {len(chunks)} chunks recuperados")
    return chunks


# ── Paso 3: Construcción del contexto ──────────────────────────────────────────

def build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        title     = c.get("doc_title", "Sin título")
        category  = c.get("doc_category", "")
        url       = c.get("doc_url", "")
        sim       = c.get("similarity", 0)
        published = c.get("doc_published", "")
        topics    = c.get("doc_topics") or []
        content   = c.get("content", "")

        parts.append(
            f"[FRAGMENTO {i}] — similitud {sim:.0%}\n"
            f"Fuente    : {title}\n"
            f"Categoría : {category}  |  Publicado: {published}\n"
            f"Temas     : {', '.join(topics) if topics else '—'}\n"
            f"URL       : {url}\n"
            f"{'─'*40}\n"
            f"{content}\n"
        )
    return "\n\n".join(parts)


# ── Paso 4: Análisis regulatorio ───────────────────────────────────────────────

def analyze(claude, requirement: str, cls: Classification, context: str) -> str:
    user_msg = (
        f"REQUERIMIENTO A ANALIZAR:\n{requirement}\n\n"
        f"PRODUCTO/MÓDULO IDENTIFICADO:\n{cls.product_description}\n\n"
        f"INDUSTRIA: {cls.industry}  |  TEMAS REGULATORIOS: {', '.join(cls.topics) or '—'}\n\n"
        f"{'='*60}\n"
        f"FRAGMENTOS DE REGULACIONES APLICABLES:\n\n"
        f"{context}\n\n"
        f"{'='*60}\n\n"
        f"Analizá qué regulaciones aplican a este requerimiento y qué debe verificar el equipo QA."
    )

    response = claude.messages.create(
        model=CLAUDE_ANALYZER,
        max_tokens=3000,
        system=ANALYZER_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


# ── Resultado ──────────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    requirement: str
    classification: Classification
    analysis: str
    sources: list[dict] = field(default_factory=list)
    chunks_used: int = 0


# ── Función principal ──────────────────────────────────────────────────────────

def analyze_requirement(
    requirement: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    industry_override: Optional[str] = None,
    topics_override: Optional[list[str]] = None,
) -> AnalysisResult:
    """
    Analiza un requerimiento y retorna las regulaciones aplicables.

    Args:
        requirement      : descripción del requerimiento/feature en texto libre
        top_k            : máximo de chunks a recuperar
        threshold        : similitud coseno mínima (0-1)
        industry_override: forzar industria sin clasificación automática
        topics_override  : forzar topics sin clasificación automática

    Returns:
        AnalysisResult con clasificación, análisis y fuentes
    """
    sb, voyage, claude = get_clients()

    # 1. Clasificar
    cls = classify_requirement(claude, requirement, industry_override, topics_override)

    if cls.industry == "ninguna":
        return AnalysisResult(
            requirement=requirement,
            classification=cls,
            analysis=(
                "No se identificó industria regulatoria aplicable para este requerimiento. "
                "Revisá si corresponde a banca (BCP) o telecomunicaciones (CONATEL)."
            ),
        )

    # 2. Embed + búsqueda
    log.info("Generando embedding...")
    q_vec = embed_query(voyage, cls.search_query)
    chunks = search_regulations(sb, q_vec, cls, top_k, threshold)

    if not chunks:
        return AnalysisResult(
            requirement=requirement,
            classification=cls,
            analysis=(
                f"No se encontraron regulaciones relevantes para los topics: {cls.topics}. "
                "Puede que aún no estén embedadas o que el requerimiento sea muy específico. "
                "Intentá ampliar los topics o reducir el threshold."
            ),
        )

    # 3. Contexto
    context = build_context(chunks)

    # 4. Análisis
    log.info("Generando análisis regulatorio...")
    analysis_text = analyze(claude, requirement, cls, context)

    # 5. Fuentes únicas ordenadas por similitud
    seen: set[str] = set()
    sources = []
    for c in chunks:
        url = c.get("doc_url", "")
        if url not in seen:
            seen.add(url)
            sources.append({
                "title":     c.get("doc_title", ""),
                "url":       url,
                "category":  c.get("doc_category", ""),
                "published": c.get("doc_published", ""),
                "topics":    c.get("doc_topics") or [],
                "similarity": round(c.get("similarity", 0), 4),
            })

    return AnalysisResult(
        requirement=requirement,
        classification=cls,
        analysis=analysis_text,
        sources=sources,
        chunks_used=len(chunks),
    )


# ── Salida formateada ──────────────────────────────────────────────────────────

def print_result(result: AnalysisResult):
    cls = result.classification
    print(f"\n{'═'*70}")
    print(f"📋 REQUERIMIENTO")
    print(f"{'─'*70}")
    print(result.requirement)
    print(f"\n{'─'*70}")
    print(f"🏷️  CLASIFICACIÓN AUTOMÁTICA")
    print(f"{'─'*70}")
    print(f"  Industria : {cls.industry}  (confianza: {cls.confidence})")
    print(f"  Producto  : {cls.product_description}")
    print(f"  Topics    : {', '.join(cls.topics) if cls.topics else '—'}")
    print(f"\n{'─'*70}")
    print(f"⚖️  ANÁLISIS REGULATORIO  ({result.chunks_used} fragmentos consultados)")
    print(f"{'─'*70}")
    print(result.analysis)

    if result.sources:
        print(f"\n{'─'*70}")
        print(f"📚 FUENTES REGULATORIAS")
        print(f"{'─'*70}")
        for s in result.sources:
            topics_str = f"  [{', '.join(s['topics'][:3])}]" if s['topics'] else ""
            print(f"  {s['similarity']:.0%}  {s['title']}{topics_str}")
            print(f"       {s['url']}")
    print(f"{'═'*70}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def interactive_cli():
    print("═" * 70)
    print("  RAG Analyzer — Regulaciones BCP / CONATEL Paraguay")
    print("  Escribí un requerimiento para ver qué regulaciones aplican.")
    print("  'salir' para terminar.")
    print("═" * 70)

    while True:
        print()
        try:
            req = input("Requerimiento: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not req:
            continue
        if req.lower() in ("salir", "exit", "quit"):
            break

        try:
            result = analyze_requirement(req)
            print_result(result)
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analiza requerimientos y busca regulaciones BCP/CONATEL aplicables"
    )
    parser.add_argument("requirement", nargs="?",
                        help="Requerimiento a analizar (si se omite, modo interactivo)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help=f"Chunks a recuperar (default: {DEFAULT_TOP_K})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Similitud mínima 0-1 (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--industry", choices=["banca", "telecomunicaciones", "ambas"],
                        help="Forzar industria sin clasificación automática")
    parser.add_argument("--topics", type=str,
                        help="Forzar topics separados por coma, ej: transferencias,riesgo")
    parser.add_argument("--json", action="store_true",
                        help="Salida en JSON (útil para integración con otras herramientas)")
    args = parser.parse_args()

    topics_list = [t.strip() for t in args.topics.split(",")] if args.topics else None

    if args.requirement:
        result = analyze_requirement(
            args.requirement,
            top_k=args.top_k,
            threshold=args.threshold,
            industry_override=args.industry,
            topics_override=topics_list,
        )
        if args.json:
            import dataclasses
            print(json.dumps({
                "requirement":   result.requirement,
                "industry":      result.classification.industry,
                "topics":        result.classification.topics,
                "product":       result.classification.product_description,
                "confidence":    result.classification.confidence,
                "analysis":      result.analysis,
                "chunks_used":   result.chunks_used,
                "sources":       result.sources,
            }, ensure_ascii=False, indent=2))
        else:
            print_result(result)
    else:
        interactive_cli()
