"""
query.py — Motor de consulta RAG para regulaciones BCP

Flujo:
  1. Recibe pregunta del usuario
  2. Genera embedding con Voyage AI (voyage-3)
  3. Busca chunks similares en Supabase pgvector (función match_bcp_chunks)
  4. Construye prompt con contexto + pregunta
  5. Claude genera respuesta fundamentada con citas
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

SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_SERVICE_KEY"]
VOYAGE_API_KEY  = os.environ["VOYAGE_API_KEY"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]

VOYAGE_MODEL    = "voyage-3"
CLAUDE_MODEL    = "claude-sonnet-4-20250514"

DEFAULT_TOP_K   = 6      # chunks a recuperar
DEFAULT_THRESHOLD = 0.45  # similitud mínima coseno

SYSTEM_PROMPT = """Sos un asistente especializado en regulaciones del Banco Central del Paraguay (BCP).

Tu función es responder preguntas sobre normativas, resoluciones, circulares y reglamentos del BCP
utilizando únicamente los fragmentos de documentos oficiales que se te proporcionan como contexto.

Reglas:
1. Respondé SOLO con información presente en el contexto provisto.
2. Si el contexto no contiene suficiente información, indicalo claramente.
3. Citá siempre la fuente (título del documento y/o URL) al final de cada afirmación relevante.
4. Usá lenguaje claro y preciso, adecuado para profesionales bancarios y de compliance.
5. Si la pregunta involucra interpretación legal, aclará que tu respuesta es informativa y no
   constituye asesoramiento legal.
6. Respondé en español.
"""


@dataclass
class QueryResult:
    answer: str
    sources: list[dict]        # [{title, url, category, similarity}]
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
    """Genera embedding para la pregunta del usuario."""
    result = voyage.embed(
        [question],
        model=VOYAGE_MODEL,
        input_type="query",   # importante: 'query' vs 'document'
    )
    return result.embeddings[0]


def search_chunks(
    sb: Client,
    query_embedding: list[float],
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    category: Optional[str] = None,
) -> list[dict]:
    """
    Llama a match_rag_chunks RPC (schema unificado) filtrando source='bcp'.
    Retorna los chunks más similares con metadata.
    """
    params = {
        "query_embedding": query_embedding,
        "match_count":     top_k,
        "match_threshold": threshold,
        "filter_source":   "bcp",
    }
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
    """
    Formatea los chunks recuperados como contexto para Claude.
    Cada chunk incluye su fuente para facilitar las citas.
    """
    parts = []
    for i, chunk in enumerate(chunks, 1):
        title    = chunk.get("doc_title", "Sin título")
        category = chunk.get("doc_category", "")
        url      = chunk.get("doc_url", "")
        sim      = chunk.get("similarity", 0)
        content  = chunk.get("content", "")

        parts.append(
            f"[FRAGMENTO {i}]\n"
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
) -> str:
    """Genera la respuesta usando Claude con el contexto recuperado."""
    user_message = (
        f"Contexto (fragmentos de regulaciones BCP):\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"Pregunta: {question}"
    )

    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text


# ── Query pública ──────────────────────────────────────────────────────────────

def query(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    category: Optional[str] = None,
) -> QueryResult:
    """
    Consulta completa RAG.

    Args:
        question: pregunta en lenguaje natural
        top_k: número de chunks a recuperar
        threshold: similitud mínima (0-1)
        category: filtrar por categoría ('resolucion', 'circular', etc.)

    Returns:
        QueryResult con respuesta, fuentes y metadata
    """
    sb, voyage, claude = get_clients()

    log.info(f"Query: {question}")

    # 1. Embedding de la pregunta
    log.info("Generando embedding...")
    q_embedding = embed_query(voyage, question)

    # 2. Búsqueda semántica
    log.info(f"Buscando chunks (top_k={top_k}, threshold={threshold})...")
    chunks = search_chunks(sb, q_embedding, top_k, threshold, category)

    if not chunks:
        return QueryResult(
            answer="No encontré regulaciones del BCP relacionadas con tu consulta en la base de datos. "
                   "Es posible que el documento relevante aún no haya sido indexado.",
            sources=[],
            chunks_used=0,
            query=question,
        )

    log.info(f"{len(chunks)} chunks recuperados")

    # 3. Construir contexto
    context = build_context(chunks)

    # 4. Generar respuesta con Claude
    log.info("Generando respuesta con Claude...")
    answer = generate_answer(claude, question, context)

    # 5. Extraer fuentes únicas
    seen_urls: set[str] = set()
    sources = []
    for chunk in chunks:
        url = chunk.get("doc_url", "")
        if url not in seen_urls:
            seen_urls.add(url)
            sources.append({
                "title":      chunk.get("doc_title", ""),
                "url":        url,
                "category":   chunk.get("doc_category", ""),
                "source":     chunk.get("doc_source", "bcp"),
                "similarity": round(chunk.get("similarity", 0), 4),
            })

    return QueryResult(
        answer=answer,
        sources=sources,
        chunks_used=len(chunks),
        query=question,
    )


# ── CLI interactivo ────────────────────────────────────────────────────────────

def interactive_cli():
    """Modo interactivo para probar el RAG desde la terminal."""
    print("=" * 60)
    print("RAG - Regulaciones BCP")
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
            result = query(question)
            print(f"\n{'─'*60}")
            print(result.answer)
            print(f"\n📚 Fuentes ({result.chunks_used} fragmentos usados):")
            for s in result.sources:
                print(f"  [{s['category']}] {s['title']} ({s['similarity']:.0%})")
                print(f"  → {s['url']}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Consulta RAG - Regulaciones BCP")
    parser.add_argument("question", nargs="?", help="Pregunta (si se omite, modo interactivo)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--category",
        choices=["resolucion", "circular", "reglamento", "norma_prudencial"],
    )
    args = parser.parse_args()

    if args.question:
        result = query(
            args.question,
            top_k=args.top_k,
            threshold=args.threshold,
            category=args.category,
        )
        print(f"\n{result.answer}\n")
        print("Fuentes:")
        for s in result.sources:
            print(f"  [{s['category']}] {s['title']} → {s['url']}")
    else:
        interactive_cli()
