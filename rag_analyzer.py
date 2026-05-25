"""
rag_analyzer.py — Analiza requerimientos y devuelve regulaciones aplicables.

Flujo:
  1. Recibe requerimiento/feature en texto libre
  2. Clasificador (keyword rules o Claude Haiku si hay ANTHROPIC_API_KEY)
     → industry + topics + search_query
  3. Voyage AI embeds search_query → vector
  4. pgvector busca chunks filtrados por industry + topics
  5. Si hay ANTHROPIC_API_KEY: Claude Sonnet genera análisis narrativo
     Si no: imprime chunks formateados directamente (igual de útil para QA)

Uso:
  python rag_analyzer.py "El sistema debe permitir transferencias SIPAP 24/7"
  python rag_analyzer.py --interactive
  python rag_analyzer.py --industry banca --topics transferencias,riesgo "..."
  python rag_analyzer.py --json "..."
"""

import argparse
import json
import logging
import os
import re
import unicodedata
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
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")  # opcional

VOYAGE_MODEL      = "voyage-3"
CLAUDE_CLASSIFIER = "claude-haiku-4-5-20251014"
CLAUDE_ANALYZER   = "claude-sonnet-4-5-20251022"

DEFAULT_TOP_K     = 10
DEFAULT_THRESHOLD = 0.38

HAS_CLAUDE = bool(ANTHROPIC_KEY)

# ── Taxonomía ──────────────────────────────────────────────────────────────────

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

# ── Clasificador por keywords (sin API) ────────────────────────────────────────
#
# Mapa: topic → lista de keywords que activan ese topic en el requerimiento.
# El orden importa: keywords más específicos primero.

KEYWORD_MAP: dict[str, list[str]] = {
    # Banca
    "transferencias":     ["sipap", "spi", "transferencia", "pago interbancario",
                           "remesa", "acreditación", "débito automático", "transferir"],
    "atm":                ["atm", "cajero automático", "cajero", "dispensador"],
    "tarjetas":           ["tarjeta de crédito", "tarjeta de débito", "tarjeta prepago",
                           "tarjeta", "plástico", "pos", "punto de venta"],
    "cuenta_corriente":   ["cuenta corriente", "cuentas corrientes", "cta cte",
                           "cuenta de depósito", "cuentas de depósito",
                           "cuenta de deposito", "cuentas de depositos"],
    "cuenta_basica":      ["cuenta básica", "cuentas básicas", "cuenta básica de ahorro",
                           "cuentas básicas de ahorro", "cuenta basica",
                           "cuenta simplificada", "cuenta básica de ahorro"],
    "capital":            ["capital mínimo", "solvencia", "patrimonio", "capital regulatorio",
                           "adecuación de capital", "basilea"],
    "cambios":            ["tipo de cambio", "divisa", "moneda extranjera", "dólar",
                           "euro", "casa de cambio", "fx"],
    "auditoria":          ["auditoría", "auditor externo", "informe de auditoría", "revisión"],
    "riesgo":             ["riesgo operacional", "riesgo de crédito", "riesgo de mercado",
                           "riesgo de liquidez", "gestión de riesgo", "riesgo"],
    "fraude_seguridad":   ["fraude", "seguridad", "ciberseguridad", "phishing",
                           "autenticación", "doble factor", "2fa", "otp", "pin"],
    "tecnologia":         ["nube", "cloud", "api", "sistema", "plataforma digital",
                           "automatización", "microservicio", "software"],
    "firma_digital":      ["firma digital", "firma electrónica", "certificado digital"],
    "reporto":            ["reporto", "repo", "operaciones de reporto"],
    "tasas_interes":      ["tasa de interés", "tasa activa", "tasa pasiva", "tna", "tea",
                           "tasa nominal", "interés"],
    "tercerizacion":      ["tercerización", "tercerizacion", "outsourcing",
                           "proveedor externo", "servicio tercerizado",
                           "proveedor de servicios tecnológicos"],
    "credito_cartera":    ["crédito", "préstamo", "microcrédito", "hipoteca",
                           "hipotecario", "crédito hipotecario", "crédito de consumo",
                           "línea de crédito", "financiamiento", "cartera",
                           "cuota ingreso", "cuota/ingreso", "relación cuota",
                           "score crediticio", "riesgo crediticio"],
    "depositos":          ["depósito", "ahorro", "plazo fijo", "caja de ahorro",
                           "certificado de depósito"],
    "contabilidad":       ["contabilidad", "balance", "estado financiero",
                           "plan de cuentas", "registro contable"],
    "liquidez":           ["liquidez", "encaje", "encaje legal", "reserva"],
    "aml":                ["lavado", "antilavado", "aml", "kyc", "conozca su cliente",
                           "prevención de lavado", "financiamiento del terrorismo",
                           "uif", "reporte de operación"],
    "gobierno_corporativo": ["gobierno corporativo", "directorio", "junta directiva",
                              "comité de auditoría", "código de ética"],
    "mercado_capitales":  ["mercado de capitales", "bolsa", "acciones", "bonos",
                           "fondo de inversión", "fondo mutuo", "fideicomiso"],
    "seguros":            ["seguro", "póliza", "aseguradora", "reaseguro"],
    "cheques":            ["cheque", "cámara compensadora", "compensación de cheques"],
    "disolucion_entidades": ["disolución", "liquidación", "intervención bancaria"],
    "asesoria_financiera": ["asesoría financiera", "asesor financiero", "agente de bolsa"],
    "seguro_depositos":   ["fondo de garantía", "seguro de depósitos", "garantía de depósitos"],
    # Telecom
    "espectro":           ["espectro", "frecuencia", "banda de frecuencia",
                           "espectro radioeléctrico", "interferencia"],
    "concesiones":        ["concesión", "licencia", "autorización", "habilitación",
                           "permiso de operación"],
    "internet":           ["internet", "banda ancha", "acceso a internet", "isp",
                           "fibra óptica", "datos móviles"],
    "telefonia":          ["telefonía", "celular", "móvil", "móviles", "red móvil",
                           "portabilidad", "portabilidad numérica", "operadora",
                           "operadoras móviles"],
    "radiodifusion":      ["televisión", "radio", "radiodifusión", "señal de tv", "cable"],
    "tarifas":            ["tarifa", "precio del servicio", "cargo de acceso"],
    "interconexion":      ["interconexión", "acceso a red", "interconnect"],
}

# Palabras que indican industria
BANCA_SIGNALS    = ["banco", "financiera", "bcp", "superintendencia de bancos",
                    "entidad financiera", "sipap", "spi", "transferencia bancaria",
                    "cuenta", "depósito", "crédito", "tarjeta", "atm", "cajero"]
TELECOM_SIGNALS  = ["conatel", "telecom", "telecomunicaciones", "internet", "celular",
                    "móvil", "móviles", "operadora", "señal", "espectro", "frecuencia",
                    "televisión", "radio", "fibra óptica", "isp", "portabilidad numérica"]


def _normalize(s: str) -> str:
    """Lowercase + strip accents → accent-insensitive Spanish matching."""
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()


# Pre-normalized keyword lists (built once at import, O(1) per lookup)
_KEYWORD_MAP_NORM: dict[str, list[str]] = {
    topic: [_normalize(kw) for kw in kws]
    for topic, kws in KEYWORD_MAP.items()
}
_BANCA_SIGNALS_NORM   = [_normalize(kw) for kw in BANCA_SIGNALS]
_TELECOM_SIGNALS_NORM = [_normalize(kw) for kw in TELECOM_SIGNALS]


def classify_keywords(requirement: str) -> "Classification":
    """Clasificador determinístico por keywords. No requiere API."""
    text = _normalize(requirement)   # accent-insensitive

    # 1. Detectar industria
    banca_score   = sum(1 for kw in _BANCA_SIGNALS_NORM   if kw in text)
    telecom_score = sum(1 for kw in _TELECOM_SIGNALS_NORM  if kw in text)

    if banca_score > telecom_score:
        industry = "banca"
    elif telecom_score > banca_score:
        industry = "telecomunicaciones"
    elif banca_score > 0 and telecom_score > 0:
        industry = "ambas"
    else:
        # fallback: si menciona montos/pagos/usuarios → banca
        if re.search(r'\b(monto|pago|cuenta|usuario|cliente)\b', text):
            industry = "banca"
        else:
            industry = "ninguna"

    # 2. Detectar topics
    topics = []
    for topic, keywords in _KEYWORD_MAP_NORM.items():
        if any(kw in text for kw in keywords):
            # Filtrar topics coherentes con la industria detectada
            if industry == "banca" and topic in TOPICS_BANCA:
                topics.append(topic)
            elif industry == "telecomunicaciones" and topic in TOPICS_TELECOM:
                topics.append(topic)
            elif industry == "ambas":
                topics.append(topic)
            elif industry == "ninguna":
                topics.append(topic)

    # 3. Agregar AML automáticamente si hay montos grandes (>500K guaraníes = umbral UIF)
    if re.search(r'\b(\d[\d.,]*)\s*(millones?|mm|m)\b', text, re.I):
        if "aml" not in topics and industry in ("banca", "ambas"):
            topics.append("aml")

    # 4. Descripción del producto (heurística simple)
    product = _extract_product(requirement)

    # 5. Search query: el requerimiento original + términos regulatorios clave
    topic_terms = " ".join(t.replace("_", " ") for t in topics[:4])
    search_query = f"{requirement}. Regulación {industry}: {topic_terms}."

    return Classification(
        industry=industry,
        topics=topics,
        product_description=product,
        search_query=search_query,
        confidence="media",
    )


def _extract_product(text: str) -> str:
    """Extrae una descripción corta del producto del requerimiento."""
    # Buscar patrones comunes
    patterns = [
        r'módulo\s+de\s+[\w\s]+',
        r'sistema\s+de\s+[\w\s]+',
        r'funcionalidad\s+de\s+[\w\s]+',
        r'servicio\s+de\s+[\w\s]+',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(0)[:80].strip()
    # fallback: primeras 60 chars
    return text[:60].rstrip(".,;") + "..."


# ── Prompts Claude (si disponible) ────────────────────────────────────────────

CLASSIFIER_SYSTEM = f"""Sos un experto en regulaciones financieras y de telecomunicaciones de Paraguay.
Analizá el requerimiento y devolvé SOLO un JSON válido:
{{
  "industry": "<banca|telecomunicaciones|ambas|ninguna>",
  "topics": ["<topic>"],
  "product_description": "<descripción breve en 1 línea>",
  "search_query": "<consulta regulatoria en 1-2 oraciones>",
  "confidence": "<alta|media|baja>"
}}

Topics banca: {', '.join(TOPICS_BANCA)}
Topics telecom: {', '.join(TOPICS_TELECOM)}
Usá SOLO topics de esas listas."""

ANALYZER_SYSTEM = """Sos un especialista en compliance regulatorio de Paraguay (BCP y CONATEL).
Analizá el requerimiento e identificá qué regulaciones aplican.

Estructura tu respuesta así:

## Regulaciones aplicables
[Lista las normas directamente relevantes con número y tema]

## Obligaciones que el sistema debe cumplir
[Puntos concretos derivados de las normas — qué debe hacer o no hacer el sistema]

## Checklist QA — qué deben verificar los casos de prueba
[Lista numerada de verificaciones concretas para el equipo de testing]

## Gaps / Riesgos regulatorios
[Si algún aspecto del requerimiento no está cubierto por las normas encontradas]

Citá siempre la fuente (título + URL). Respondé en español."""


# ── Clientes ───────────────────────────────────────────────────────────────────

def get_voyage():
    import voyageai
    return voyageai.Client(api_key=VOYAGE_API_KEY)

def get_supabase():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_claude():
    if not HAS_CLAUDE:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Classification:
    industry: str
    topics: list[str]
    product_description: str
    search_query: str
    confidence: str


@dataclass
class AnalysisResult:
    requirement: str
    classification: Classification
    analysis: str
    sources: list[dict] = field(default_factory=list)
    chunks_used: int = 0
    mode: str = "chunks"   # "chunks" | "claude"


# ── Paso 1: Clasificación ──────────────────────────────────────────────────────

def classify_requirement(
    requirement: str,
    industry_override: Optional[str] = None,
    topics_override: Optional[list[str]] = None,
) -> Classification:

    if industry_override and topics_override:
        return Classification(
            industry=industry_override,
            topics=topics_override,
            product_description="(override manual)",
            search_query=requirement,
            confidence="alta",
        )

    if HAS_CLAUDE:
        log.info("Clasificando con Claude Haiku...")
        claude = get_claude()
        response = claude.messages.create(
            model=CLAUDE_CLASSIFIER,
            max_tokens=512,
            system=CLASSIFIER_SYSTEM,
            messages=[{"role": "user", "content": f"Requerimiento:\n\n{requirement}"}],
        )
        raw = response.content[0].text.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        cls = Classification(
            industry=data.get("industry", "ninguna"),
            topics=[t for t in data.get("topics", []) if t in ALL_TOPICS],
            product_description=data.get("product_description", ""),
            search_query=data.get("search_query", requirement),
            confidence=data.get("confidence", "media"),
        )
    else:
        log.info("Clasificando con reglas de keywords (sin API)...")
        cls = classify_keywords(requirement)

    log.info(f"  industry={cls.industry} | topics={cls.topics}")
    log.info(f"  producto: {cls.product_description}")
    return cls


# ── Paso 2: Embed + búsqueda vectorial ────────────────────────────────────────

def embed_query(voyage, text: str) -> list[float]:
    result = voyage.embed([text], model=VOYAGE_MODEL, input_type="query")
    return result.embeddings[0]


def search_regulations(sb, query_vec: list[float], cls: Classification,
                        top_k: int, threshold: float) -> list[dict]:

    filter_industry = cls.industry if cls.industry in ("banca", "telecomunicaciones") else None
    filter_topics   = cls.topics if cls.topics else None

    params = {
        "query_embedding": query_vec,
        "match_count":     top_k,
        "match_threshold": threshold,
    }
    if filter_industry:
        params["filter_industry"] = filter_industry
    if filter_topics:
        params["filter_topics"] = filter_topics

    log.info(f"Buscando (industry={filter_industry}, topics={filter_topics}, top_k={top_k})...")
    try:
        chunks = sb.rpc("match_rag_chunks_v2", params).execute().data or []
    except Exception as e:
        log.error(f"Error RPC: {e}")
        return []

    # Fallback sin filtro de topics si hay pocos resultados
    if len(chunks) < 3 and filter_topics:
        log.info(f"  {len(chunks)} resultados, ampliando sin filtro topics...")
        params_wide = {k: v for k, v in params.items() if k != "filter_topics"}
        try:
            chunks = sb.rpc("match_rag_chunks_v2", params_wide).execute().data or []
        except Exception:
            pass

    log.info(f"  {len(chunks)} chunks encontrados")
    return chunks


# ── Paso 3: Análisis ──────────────────────────────────────────────────────────

def build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        title     = c.get("doc_title", "Sin título")
        category  = c.get("doc_category", "")
        url       = c.get("doc_url", "")
        sim       = c.get("similarity", 0)
        published = c.get("doc_published", "") or ""
        topics    = c.get("doc_topics") or []
        content   = c.get("content", "")
        parts.append(
            f"[FRAGMENTO {i}] — {sim:.0%} similitud\n"
            f"Fuente    : {title}\n"
            f"Categoría : {category}  |  Fecha: {published}\n"
            f"Temas     : {', '.join(topics[:5]) if topics else '—'}\n"
            f"URL       : {url}\n"
            f"{'─'*50}\n"
            f"{content}\n"
        )
    return "\n\n".join(parts)


def analyze_with_claude(claude, requirement: str, cls: Classification,
                         context: str) -> str:
    user_msg = (
        f"REQUERIMIENTO:\n{requirement}\n\n"
        f"PRODUCTO: {cls.product_description}\n"
        f"INDUSTRIA: {cls.industry}  |  TEMAS: {', '.join(cls.topics) or '—'}\n\n"
        f"{'='*60}\n"
        f"REGULACIONES ENCONTRADAS:\n\n{context}\n"
        f"{'='*60}\n\n"
        f"Analizá qué regulaciones aplican y generá el checklist QA."
    )
    response = claude.messages.create(
        model=CLAUDE_ANALYZER,
        max_tokens=3000,
        system=ANALYZER_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


def format_chunks_as_analysis(requirement: str, cls: Classification,
                                chunks: list[dict]) -> str:
    """Formatea los chunks como análisis estructurado (sin LLM)."""
    lines = []
    lines.append("## Regulaciones encontradas\n")

    seen_docs: dict[str, dict] = {}
    for c in chunks:
        url = c.get("doc_url", "")
        if url not in seen_docs:
            seen_docs[url] = c

    for c in seen_docs.values():
        title     = c.get("doc_title", "Sin título")
        category  = c.get("doc_category", "")
        published = c.get("doc_published", "") or ""
        url       = c.get("doc_url", "")
        sim       = c.get("similarity", 0)
        lines.append(f"- **[{category.upper()}]** {title} ({sim:.0%})")
        if published:
            lines.append(f"  Fecha: {published}")
        lines.append(f"  URL: {url}")

    lines.append("\n## Fragmentos regulatorios relevantes\n")
    for i, c in enumerate(chunks, 1):
        title   = c.get("doc_title", "")
        sim     = c.get("similarity", 0)
        content = c.get("content", "")
        # Mostrar sólo los primeros 600 chars de cada chunk
        snippet = content[:600].rsplit(" ", 1)[0] + "..." if len(content) > 600 else content
        lines.append(f"### [{i}] {title} — {sim:.0%}")
        lines.append(snippet)
        lines.append("")

    lines.append("\n---")
    lines.append(f"_Análisis automático basado en búsqueda semántica._")
    lines.append(f"_Para análisis narrativo completo, configurá ANTHROPIC_API_KEY._")

    return "\n".join(lines)


# ── Función principal ──────────────────────────────────────────────────────────

def analyze_requirement(
    requirement: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    industry_override: Optional[str] = None,
    topics_override: Optional[list[str]] = None,
) -> AnalysisResult:

    voyage = get_voyage()
    sb     = get_supabase()
    claude = get_claude()

    # 1. Clasificar
    cls = classify_requirement(requirement, industry_override, topics_override)

    if cls.industry == "ninguna":
        return AnalysisResult(
            requirement=requirement,
            classification=cls,
            analysis="No se identificó industria regulatoria. ¿Es banca (BCP) o telecomunicaciones (CONATEL)?",
            mode="chunks",
        )

    # 2. Embed + buscar
    log.info("Generando embedding del requerimiento...")
    q_vec  = embed_query(voyage, cls.search_query)
    chunks = search_regulations(sb, q_vec, cls, top_k, threshold)

    if not chunks:
        return AnalysisResult(
            requirement=requirement,
            classification=cls,
            analysis=(
                f"No se encontraron regulaciones para industry={cls.industry}, "
                f"topics={cls.topics}. Probá con --threshold 0.30 o ampliá los topics."
            ),
            mode="chunks",
        )

    # 3. Análisis
    context = build_context(chunks)

    if claude:
        log.info("Generando análisis con Claude Sonnet...")
        analysis = analyze_with_claude(claude, requirement, cls, context)
        mode = "claude"
    else:
        log.info("Formateando regulaciones encontradas (modo sin API)...")
        analysis = format_chunks_as_analysis(requirement, cls, chunks)
        mode = "chunks"

    # 4. Fuentes únicas
    seen: set[str] = set()
    sources = []
    for c in chunks:
        url = c.get("doc_url", "")
        if url not in seen:
            seen.add(url)
            sources.append({
                "title":      c.get("doc_title", ""),
                "url":        url,
                "category":   c.get("doc_category", ""),
                "published":  c.get("doc_published", ""),
                "topics":     c.get("doc_topics") or [],
                "similarity": round(c.get("similarity", 0), 4),
            })

    return AnalysisResult(
        requirement=requirement,
        classification=cls,
        analysis=analysis,
        sources=sources,
        chunks_used=len(chunks),
        mode=mode,
    )


# ── Salida formateada ──────────────────────────────────────────────────────────

def print_result(result: AnalysisResult):
    cls  = result.classification
    mode = "🤖 Claude Sonnet" if result.mode == "claude" else "🔍 Búsqueda semántica"

    print(f"\n{'═'*70}")
    print(f"📋 REQUERIMIENTO")
    print(f"{'─'*70}")
    print(result.requirement)

    print(f"\n{'─'*70}")
    print(f"🏷️  CLASIFICACIÓN  (confianza: {cls.confidence})")
    print(f"{'─'*70}")
    print(f"  Industria : {cls.industry}")
    print(f"  Producto  : {cls.product_description}")
    print(f"  Topics    : {', '.join(cls.topics) if cls.topics else '—'}")

    print(f"\n{'─'*70}")
    print(f"⚖️  ANÁLISIS  [{mode}]  —  {result.chunks_used} fragmentos")
    print(f"{'─'*70}")
    print(result.analysis)

    if result.sources:
        print(f"\n{'─'*70}")
        print(f"📚 FUENTES  ({len(result.sources)} documentos)")
        print(f"{'─'*70}")
        for s in result.sources:
            t_str = f"  [{', '.join(s['topics'][:3])}]" if s['topics'] else ""
            print(f"  {s['similarity']:.0%}  [{s['category']}] {s['title']}{t_str}")
            print(f"       {s['url']}")

    print(f"{'═'*70}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def interactive_cli():
    print("═" * 70)
    print("  RAG Analyzer — Regulaciones BCP / CONATEL Paraguay")
    print(f"  Modo: {'Claude Sonnet (análisis narrativo)' if HAS_CLAUDE else 'Búsqueda semántica (sin API key)'}")
    print("  Ingresá un requerimiento. 'salir' para terminar.")
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
        description="Analiza requerimientos → regulaciones BCP/CONATEL aplicables"
    )
    parser.add_argument("requirement", nargs="?",
                        help="Requerimiento a analizar (omitir = modo interactivo)")
    parser.add_argument("--top-k",     type=int,   default=DEFAULT_TOP_K)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--industry",  choices=["banca", "telecomunicaciones", "ambas"])
    parser.add_argument("--topics",    type=str,
                        help="Topics forzados, separados por coma: transferencias,riesgo")
    parser.add_argument("--json",      action="store_true",
                        help="Salida en JSON (para integración con otras herramientas)")
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
            print(json.dumps({
                "requirement": result.requirement,
                "industry":    result.classification.industry,
                "topics":      result.classification.topics,
                "product":     result.classification.product_description,
                "confidence":  result.classification.confidence,
                "analysis":    result.analysis,
                "chunks_used": result.chunks_used,
                "mode":        result.mode,
                "sources":     result.sources,
            }, ensure_ascii=False, indent=2))
        else:
            print_result(result)
    else:
        interactive_cli()
