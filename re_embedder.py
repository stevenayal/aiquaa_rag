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
from pathlib import Path
from typing import Optional

import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

from dotenv import load_dotenv
from supabase import create_client, Client

_root = Path(__file__).parent if "__file__" in dir() else Path(".")
for _env in [_root / ".env", _root / "BCP" / ".env", _root / "CONATEL" / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

VOYAGE_MODEL  = "voyage-3"
EMBED_DELAY   = 22.0  # segundos entre lotes (free tier: 3 RPM = 1 req/20s)
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


def get_doc_ids(sb: Client,
                source: Optional[str],
                category: Optional[str],
                year: Optional[int]) -> list[str]:
    """Build list of doc_ids matching filters."""
    q = sb.table("rag_documents").select("id")
    if source:
        q = q.eq("source", source)
    if category:
        q = q.eq("category", category)
    # Paginate — recreate query each page to avoid param accumulation
    all_ids = []
    offset = 0
    while True:
        res = sb.table("rag_documents").select("id,title,url,filename") \
            .eq("source", source) if source else sb.table("rag_documents").select("id,title,url,filename")
        # rebuild cleanly
        res = sb.table("rag_documents").select("id,title,url,filename")
        if source:
            res = res.eq("source", source)
        if category:
            res = res.eq("category", category)
        rows = res.range(offset, offset + 999).execute().data or []
        if not rows:
            break
        if year:
            y = str(year)
            rows = [r for r in rows if (
                f".{y}" in (r.get("title") or "")
                or y in (r.get("filename") or "")
                or f"/{y}/" in (r.get("url") or "")
                or (r.get("url") or "").endswith(f"-{y}.pdf")
            )]
        all_ids.extend(r["id"] for r in rows)
        if len(rows) < 1000:
            break
        offset += 1000
    return all_ids


def fetch_pending_chunks(sb: Client,
                         doc_ids: list[str],
                         page_size: int,
                         offset: int) -> list[dict]:
    """Devuelve chunks con embedding NULL para los doc_ids dados."""
    if not doc_ids:
        return []
    res = (
        sb.table("rag_chunks")
        .select("id, content, document_id")
        .is_("embedding", "null")
        .in_("document_id", doc_ids)
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
    category: Optional[str] = None,
    year: Optional[int] = None,
    batch_size: int = 8,
    dry_run: bool = False,
):
    sb = get_supabase()

    parts = []
    if source:   parts.append(f"source={source}")
    if category: parts.append(f"category={category}")
    if year:     parts.append(f"year={year}")
    label = ", ".join(parts) if parts else "todas las fuentes"
    log.info(f"=== Re-embedder RAG [{label}] ===")

    doc_ids = get_doc_ids(sb, source, category, year)
    log.info(f"  Docs matching filters: {len(doc_ids)}")

    if not doc_ids:
        log.info("Sin docs que coincidan.")
        return

    if dry_run:
        chunk_res = (
            sb.table("rag_chunks")
            .select("id", count="exact")
            .is_("embedding", "null")
            .in_("document_id", doc_ids)
            .execute()
        )
        log.info(f"  Chunks sin embedding: {chunk_res.count or 0:,}")
        return

    voyage = get_voyage()
    total_ok = total_fail = total_processed = 0
    offset = 0

    while True:
        chunks = fetch_pending_chunks(sb, doc_ids, PAGE_SIZE, offset)
        if not chunks:
            break

        log.info(f"Página offset={offset}: {len(chunks)} chunks pendientes")
        ok, fail = embed_and_update(sb, voyage, chunks, batch_size)
        total_ok   += ok
        total_fail += fail
        total_processed += len(chunks)

        if fail > 0:
            log.warning(f"  {fail} fallos en esta página; abortando.")
            break
        # Don't advance offset: embedded chunks disappear from NULL set,
        # so always re-query from offset=0 until no chunks remain.

    log.info("\n=== Re-embedding completo ===")
    log.info(f"  ✓ Actualizados : {total_ok}")
    log.info(f"  ✗ Fallidos     : {total_fail}")
    log.info(f"  Total proceso  : {total_processed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-embedder RAG — agrega embeddings faltantes")
    parser.add_argument("--source", choices=["bcp", "conatel"],
                        help="Filtrar por fuente (default: todas)")
    parser.add_argument("--category",
                        choices=["resolucion", "circular", "reglamento",
                                 "norma_prudencial", "ley", "decreto"],
                        help="Filtrar por categoría")
    parser.add_argument("--year", type=int,
                        help="Filtrar por año (ej: 2026) — busca en título, filename, url")
    parser.add_argument("--batch-size", type=int, default=8,
                        help="Chunks por lote Voyage AI (default: 8; reducir si hay rate limits)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo contar chunks pendientes, no generar embeddings")
    args = parser.parse_args()

    run_re_embedder(
        source=args.source,
        category=args.category,
        year=args.year,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
