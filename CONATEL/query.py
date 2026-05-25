"""
query.py — Motor de consulta RAG para regulaciones CONATEL (y/o BCP)

Flujo:
  1. Pregunta del usuario
  2. Embedding con Voyage AI (voyage-3)
  3. Búsqueda vectorial en Supabase via match_rag_chunks RPC
  4. Construcción de contexto con citas
  5. Claude genera respuesta fundamentada
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
import voyageai
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────

SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_SERVICE_KEY"]
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]

VOYAGE_MODEL   = "voyage-3"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"

DEFAULT_TOP_K      = 6
DEFAULT_THRESHOLD  = 0.45

SYSTEM_PROMPT_CONATEL = """Sos un asistente especializado en regulaciones de telecomunicaciones de Paraguay,
con base en documentos oficiales de la CONATEL (Comisión Nacional de Telecomunicaciones).

Tu función es responder preguntas sobre resoluciones, reglamentos, normativas y circulares de la CONATEL
utilizando únicamente los fragmentos de documentos oficiales proporcionados como contexto.

Reglas:
1. Respondé SOLO con información presente en el contexto provisto.
2. Si el contexto no contiene suficiente información, indicalo claramente.
3. Citá siempre la fuente (título y/o URL) al final de cada afirmación relevante.
4. Usá lenguaje claro y preciso, adecuado para profesionales de telecomunicaciones y compliance.
5. Si la pregunta involucra interpretación legal, aclará que tu respuesta es informativa y no
   constituye asesoramiento legal.
6. Respondé en español.
"""

SYSTEM_PROMPT_UNIFIED = """Sos un asistente especializado en regulaciones financieras y de telecomunicaciones
de Paraguay, con base en documentos oficiales del BCP (Banco Central del Paraguay) y la CONATEL
(Comisión Nacional de Telecomunicaciones).

Tu función es responder preguntas sobre regulaciones utilizando únicamente los fragmentos de
documentos oficiales proporcionados como contexto.

Reglas:
1. Respondé SOLO con información presente en el contexto provisto.
2. Si el contexto no contiene suficiente información, indicalo claramente.
3. Citá siempre la fuente (institución, título y/o URL) al final de cada afirmación relevante.
4. Usá lenguaje claro y preciso, adecuado para profesionales de compliance.
5. Si la pregunta involucra interpretación legal, aclará que tu respuesta es informativa.
6. Respondé en español.
"""


@dataclass
class QueryResult:
    answer: str
    sources: list[dict]
    chunks_used: int
    query: str


# ── Clientes ───────────────────────────────────────────────────────────────────

def get_clients():
    sb     = create_client(SUPABASE_URL, SUPABASE_KEY)
    voyage = voyageai.Client(api_key=VOYAGE_API_KEY)
    claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    return sb, voyage, claude


# ── Búsqueda semántica ─────────────────────────────────────────────────────────

def embed_query(voyage: voyageai.Client, question: str) -> list[float]:
    result = voyage.embed([question], model=VOYAGE_MODEL, input_type="query")
    return result.embeddings[0]


def search_chunks(
    sb: Client,
    query_embedding: list[float],
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    source: Optional[str] = None,      # 'bcp', 'conatel', o None = ambos
    category: Optional[str] = None,
) -> list[dict]:
    """Llama a match_rag_chunks RPC en Supabase."""
    params: dict = {
        "query_embedding": query_embedding,
        "match_count":     top_k,
        "match_threshold": threshold,
    }
    if source:
        params["filter_source"] = source
    if category:
        params["filter_category"] = category

    try:
        res = sb.rpc("match_rag_chunks", params).execute()
        return res.data or []
    except Exception as e:
        log.error(f"Error en búsqueda vectorial: {e}")
        return []


# ── Construcción del prompt ────────────────────────────────────────────────────

def build_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        title    = chunk.get("doc_title", "Sin título")
        category = chunk.get("doc_category", "")
        url      = chunk.get("doc_url", "")
        src      = chunk.get("doc_source", "").upper()
        sim      = chunk.get("similarity", 0)
        content  = chunk.get("content", "")

        parts.append(
            f"[FRAGMENTO {i} — {src}]\n"
            f"Fuente: {title}\n"
            f"Categoría: {category}\n"
            f"URL: {url}\n"
            f"Relevancia: {sim:.2%}\n"
            f"---\n"
            f"{content}\n"
        )
    return "\n\n".join(parts)


# ── Generación con Claude ──────────────────────────────────────────────────────

def generate_answer(
    claude: anthropic.Anthropic,
    question: str,
    context: str,
    source: Optional[str] = None,
) -> str:
    system = SYSTEM_PROMPT_CONATEL if source == "conatel" else SYSTEM_PROMPT_UNIFIED
    user_msg = (
        f"Contexto (fragmentos de regulaciones oficiales):\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"Pregunta: {question}"
    )
    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


# ── Query pública ──────────────────────────────────────────────────────────────

def query(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    source: Optional[str] = "conatel",   # default: solo CONATEL
    category: Optional[str] = None,
) -> QueryResult:
    """
    Consulta RAG completa.

    Args:
        question:  pregunta en lenguaje natural
        top_k:     chunks a recuperar
        threshold: similitud mínima coseno (0-1)
        source:    'bcp', 'conatel', o None para buscar en ambos
        category:  filtrar por categoría
    """
    sb, voyage, claude = get_clients()

    log.info(f"Query [{source or 'todos'}]: {question}")

    q_embedding = embed_query(voyage, question)
    chunks = search_chunks(sb, q_embedding, top_k, threshold, source, category)

    institution = {
        "bcp":     "BCP",
        "conatel": "CONATEL",
        None:      "BCP/CONATEL",
    }.get(source, source)

    if not chunks:
        return QueryResult(
            answer=(
                f"No encontré regulaciones de {institution} relacionadas con tu consulta. "
                "Es posible que el documento relevante aún no haya sido indexado."
            ),
            sources=[],
            chunks_used=0,
            query=question,
        )

    log.info(f"{len(chunks)} chunks recuperados")
    context = build_context(chunks)
    answer  = generate_answer(claude, question, context, source)

    seen_urls: set[str] = set()
    sources = []
    for chunk in chunks:
        url = chunk.get("doc_url", "")
        if url not in seen_urls:
            seen_urls.add(url)
            sources.append({
                "title":    chunk.get("doc_title", ""),
                "url":      url,
                "category": chunk.get("doc_category", ""),
                "source":   chunk.get("doc_source", ""),
                "similarity": round(chunk.get("similarity", 0), 4),
            })

    return QueryResult(answer=answer, sources=sources, chunks_used=len(chunks), query=question)


# ── CLI interactivo ────────────────────────────────────────────────────────────

def interactive_cli(source: Optional[str] = "conatel"):
    institution = (source or "BCP + CONATEL").upper()
    print("=" * 60)
    print(f"RAG — Regulaciones {institution}")
    print("Escribe 'salir' para terminar")
    print("=" * 60)

    while True:
        print()
        question = input("Pregunta: ").strip()
        if not question:
            continue
        if question.lower() in ("salir", "exit", "quit"):
            break

        try:
            result = query(question, source=source)
            print(f"\n{'─'*60}")
            print(result.answer)
            print(f"\n📚 Fuentes ({result.chunks_used} fragmentos usados):")
            for s in result.sources:
                print(f"  [{s['source'].upper()} / {s['category']}] {s['title']} ({s['similarity']:.0%})")
                print(f"  → {s['url']}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Consulta RAG — Regulaciones CONATEL / BCP")
    parser.add_argument("question", nargs="?", help="Pregunta (sin argumento = modo interactivo)")
    parser.add_argument("--top-k",    type=int,   default=DEFAULT_TOP_K)
    parser.add_argument("--threshold",type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--source",
        choices=["bcp", "conatel"],
        default="conatel",
        help="Filtrar por fuente (default: conatel). Omitir para buscar en ambos.",
    )
    parser.add_argument(
        "--category",
        choices=["resolucion", "reglamento", "normativa", "circular"],
    )
    args = parser.parse_args()

    source = args.source  # None si el usuario quiere ambos

    if args.question:
        result = query(
            args.question,
            top_k=args.top_k,
            threshold=args.threshold,
            source=source,
            category=args.category,
        )
        print(f"\n{result.answer}\n")
        print("Fuentes:")
        for s in result.sources:
            print(f"  [{s['source'].upper()} / {s['category']}] {s['title']} → {s['url']}")
    else:
        interactive_cli(source=source)
