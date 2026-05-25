"""
re_embedder.py — Genera embeddings para chunks sin embedding en Supabase.

Uso:
  python re_embedder.py                      # todos los chunks sin embedding
  python re_embedder.py --source bcp         # solo BCP
  python re_embedder.py --source conatel     # solo CONATEL
  python re_embedder.py --batch-size 4       # lotes más pequeños (rate limits)
  python re_embedder.py --dry-run            # ver cuántos chunks quedan sin embed
"""

import argparse
import logging
import os
import time
from typing import Optional

import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

VOYAGE_MODEL  = "voyage-3"
EMBED_DELAY   = 1.0   # segundos entre lotes (free tier: 3 RPM)
PAGE_SIZE     = 50    # chunks por consulta paginada

# ── Clientes ───────────────────────────────────────────────────────────────────

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_voyage():
    import voyageai
    return voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


# ── Core ───────────────────────────────────────────────────────────────────────

def count_pending(sb: Client, source: Optional[str] = None) -> int:
    """Cuenta chunks con embedding NULL, opcionalmente filtrados por fuente."""
    query = (
        sb.table("rag_chunks")
        .select("id", count="exact")
        .is_("embedding", "null")
    )
    if source:
        # Join a través de document_id → rag_documents.source
        # Supabase no soporta JOIN en select simple; usamos RPC o SQL directo
        pass
    res = query.execute()
    return res.count or 0


def fetch_pending_chunks(sb: Client,
                         source: Optional[str],
                         page_size: int,
                         offset: int) -> list[dict]:
    """
    Devuelve chunks con embedding NULL.
    Si source especificado, filtra por rag_documents.source via join.
    """
    if source:
        # Supabase Python SDK no soporta JOIN directo; usamos execute_sql via RPC
        # Alternativa: dos pasos — fetch doc_ids, luego chunks
        res = (
            sb.table("rag_documents")
            .select("id")
            .eq("source", source)
            .execute()
        )
        doc_ids = [r["id"] for r in res.data]
        if not doc_ids:
            return []
        # Tomar subconjunto paginado de doc_ids para evitar IN muy grande
        res2 = (
            sb.table("rag_chunks")
            .select("id, content, document_id")
            .is_("embedding", "null")
            .in_("document_id", doc_ids)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        return res2.data or []
    else:
        res = (
            sb.table("rag_chunks")
            .select("id, content, document_id")
            .is_("embedding", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        return res.data or []


def embed_and_update(sb: Client, voyage, chunks: list[dict],
                     batch_size: int) -> tuple[int, int]:
    """
    Genera embeddings para `chunks` y actualiza rag_chunks.
    Retorna (ok_count, fail_count).
    """
    ok = fail = 0
    texts = [c["content"] for c in chunks]

    for i in range(0, len(texts), batch_size):
        batch_chunks = chunks[i:i+batch_size]
        batch_texts  = texts[i:i+batch_size]
        batch_num    = i // batch_size + 1
        log.info(f"  Embedding lote {batch_num} ({len(batch_texts)} chunks)...")

        try:
            result = voyage.embed(batch_texts, model=VOYAGE_MODEL, input_type="document")
            embeddings = result.embeddings
        except Exception as e:
            log.error(f"  Error embedding lote {batch_num}: {e}")
            fail += len(batch_chunks)
            time.sleep(EMBED_DELAY * 2)
            continue

        # Update uno a uno (SDK no soporta bulk update con valores distintos)
        for chunk, emb in zip(batch_chunks, embeddings):
            try:
                sb.table("rag_chunks") \
                  .update({"embedding": emb}) \
                  .eq("id", chunk["id"]) \
                  .execute()
                ok += 1
            except Exception as e:
                log.error(f"  Error update chunk {chunk['id']}: {e}")
                fail += 1

        time.sleep(EMBED_DELAY)

    return ok, fail


def run_re_embedder(
    source: Optional[str] = None,
    batch_size: int = 8,
    dry_run: bool = False,
):
    sb = get_supabase()

    label = f"source={source}" if source else "todas las fuentes"
    log.info(f"=== Re-embedder RAG [{label}] ===")

    if dry_run:
        # Conteo rápido sin source filter (SDK no soporta join COUNT)
        res = (
            sb.table("rag_chunks")
            .select("id", count="exact")
            .is_("embedding", "null")
            .execute()
        )
        total = res.count or 0
        log.info(f"Chunks sin embedding (total sin filtro fuente): {total:,}")
        if source:
            doc_res = (
                sb.table("rag_documents")
                .select("id")
                .eq("source", source)
                .execute()
            )
            doc_ids = [r["id"] for r in doc_res.data]
            chunk_res = (
                sb.table("rag_chunks")
                .select("id", count="exact")
                .is_("embedding", "null")
                .in_("document_id", doc_ids)
                .execute()
            )
            log.info(f"Chunks sin embedding [{source}]: {chunk_res.count or 0:,}")
        return

    voyage = get_voyage()
    total_ok = total_fail = total_processed = 0
    offset = 0

    while True:
        chunks = fetch_pending_chunks(sb, source, PAGE_SIZE, offset)
        if not chunks:
            break

        log.info(f"Página offset={offset}: {len(chunks)} chunks pendientes")
        ok, fail = embed_and_update(sb, voyage, chunks, batch_size)
        total_ok   += ok
        total_fail += fail
        total_processed += len(chunks)

        if len(chunks) < PAGE_SIZE:
            break
        # Si hubo fallos, no avanzar offset para reintentar en próxima corrida
        if fail == 0:
            offset += PAGE_SIZE
        else:
            log.warning(f"  {fail} fallos en esta página; reintentar sin avanzar offset.")
            break

    log.info("\n=== Re-embedding completo ===")
    log.info(f"  ✓ Actualizados : {total_ok}")
    log.info(f"  ✗ Fallidos     : {total_fail}")
    log.info(f"  Total proceso  : {total_processed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-embedder RAG — agrega embeddings faltantes")
    parser.add_argument("--source", choices=["bcp", "conatel"],
                        help="Filtrar por fuente (default: todas)")
    parser.add_argument("--batch-size", type=int, default=8,
                        help="Chunks por lote Voyage AI (default: 8; reducir si hay rate limits)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo contar chunks pendientes, no generar embeddings")
    args = parser.parse_args()

    run_re_embedder(
        source=args.source,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
