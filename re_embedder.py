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

VOYAGE_MODEL    = "voyage-3"
EMBED_DELAY     = 0.5    # segundos entre lotes (paid tier: 300 RPM)
RATE_LIMIT_WAIT = 65.0   # espera tras error de rate limit (>60s para limpiar ventana)
MAX_RETRIES     = 3      # reintentos por lote ante rate limit
PAGE_SIZE       = 500    # chunks por consulta paginada
DOC_ID_BATCH    = 200    # max doc_ids per .in_() call (Supabase URL length limit ~8KB)

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
    """Build list of doc_ids matching filters.

    Year filter uses published column (primary) — far more reliable than
    text-matching URLs/titles, since many BCP docs use 2-digit years like
    'fecha 10.04.25' and never contain '2025' in url/filename.
    """
    all_ids = []
    offset = 0
    while True:
        res = sb.table("rag_documents").select("id")
        if source:
            res = res.eq("source", source)
        if category:
            res = res.eq("category", category)
        if year:
            res = res.gte("published", f"{year}-01-01").lt("published", f"{year + 1}-01-01")
        rows = res.range(offset, offset + 999).execute().data or []
        if not rows:
            break
        all_ids.extend(r["id"] for r in rows)
        if len(rows) < 1000:
            break
        offset += 1000
    return all_ids


def fetch_pending_chunks(sb: Client,
                         doc_ids: list[str],
                         page_size: int) -> list[dict]:
    """Devuelve hasta page_size chunks con embedding NULL para los doc_ids dados.

    Batches doc_ids in groups of DOC_ID_BATCH to avoid Supabase URL length limits.
    Always call with the full doc_ids list — embedded rows drop from IS NULL set,
    so re-querying from scratch each iteration naturally pages forward.
    """
    if not doc_ids:
        return []
    all_chunks: list[dict] = []
    for i in range(0, len(doc_ids), DOC_ID_BATCH):
        batch = doc_ids[i : i + DOC_ID_BATCH]
        res = (
            sb.table("rag_chunks")
            .select("id, content, document_id")
            .is_("embedding", "null")
            .in_("document_id", batch)
            .limit(page_size - len(all_chunks))
            .execute()
        )
        all_chunks.extend(res.data or [])
        if len(all_chunks) >= page_size:
            break
    return all_chunks


def _is_rate_limit(err: Exception) -> bool:
    s = str(err).lower()
    return "rate" in s or "429" in s or "rpm" in s or "tpm" in s


def embed_and_update(sb: Client, voyage, chunks: list[dict],
                     batch_size: int) -> tuple[int, int]:
    """
    Genera embeddings para `chunks` y actualiza rag_chunks.
    Reintentos automáticos ante rate limit (hasta MAX_RETRIES veces).
    Retorna (ok_count, fail_count).
    """
    ok = fail = 0
    texts = [c["content"] for c in chunks]

    for i in range(0, len(texts), batch_size):
        batch_chunks = chunks[i:i+batch_size]
        batch_texts  = texts[i:i+batch_size]
        batch_num    = i // batch_size + 1
        log.info(f"  Embedding lote {batch_num} ({len(batch_texts)} chunks)...")

        embeddings = None
        for attempt in range(MAX_RETRIES):
            try:
                result = voyage.embed(batch_texts, model=VOYAGE_MODEL, input_type="document")
                embeddings = result.embeddings
                break
            except Exception as e:
                if _is_rate_limit(e) and attempt < MAX_RETRIES - 1:
                    wait = RATE_LIMIT_WAIT * (attempt + 1)
                    log.warning(f"  Rate limit lote {batch_num} (intento {attempt+1}), "
                                f"esperando {wait:.0f}s...")
                    time.sleep(wait)
                else:
                    log.error(f"  Error embedding lote {batch_num}: {e}")
                    fail += len(batch_chunks)
                    break

        if embeddings is None:
            continue

        # Bulk update — un solo RPC en lugar de N PATCHes individuales
        try:
            import json as _json
            updates = [
                {"id": chunk["id"], "embedding": f"[{','.join(str(x) for x in emb)}]"}
                for chunk, emb in zip(batch_chunks, embeddings)
            ]
            sb.rpc("bulk_update_embeddings", {"updates": updates}).execute()
            ok += len(batch_chunks)
        except Exception as e:
            log.error(f"  Error bulk update lote {batch_num}: {e}")
            # Fallback: update uno a uno
            for chunk, emb in zip(batch_chunks, embeddings):
                try:
                    sb.table("rag_chunks") \
                      .update({"embedding": emb}) \
                      .eq("id", chunk["id"]) \
                      .execute()
                    ok += 1
                except Exception as e2:
                    log.error(f"  Error update chunk {chunk['id']}: {e2}")
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
        # Batch doc_ids to avoid Supabase URL length limits
        total_pending = 0
        for i in range(0, len(doc_ids), DOC_ID_BATCH):
            batch = doc_ids[i : i + DOC_ID_BATCH]
            res = (
                sb.table("rag_chunks")
                .select("id", count="exact")
                .is_("embedding", "null")
                .in_("document_id", batch)
                .execute()
            )
            total_pending += res.count or 0
        log.info(f"  Chunks sin embedding: {total_pending:,}")
        return

    voyage = get_voyage()
    total_ok = total_fail = total_processed = 0
    consecutive_zero_ok = 0

    while True:
        chunks = fetch_pending_chunks(sb, doc_ids, PAGE_SIZE)
        if not chunks:
            break

        log.info(f"  {len(chunks)} chunks pendientes en esta pasada")
        ok, fail = embed_and_update(sb, voyage, chunks, batch_size)
        total_ok   += ok
        total_fail += fail
        total_processed += len(chunks)

        if ok == 0:
            consecutive_zero_ok += 1
            if consecutive_zero_ok >= 3:
                log.error("  3 pasadas consecutivas sin progreso — abortando para evitar loop.")
                break
        else:
            consecutive_zero_ok = 0

        if fail > 0:
            log.warning(f"  {fail} fallos en esta pasada; reintentando en siguiente ciclo.")
            # No break: failed chunks still have NULL embedding → re-fetched next iteration.
        # Don't advance offset: embedded chunks disappear from IS NULL set,
        # so re-querying from scratch naturally moves to the next batch.

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
                        help="Filtrar por año (ej: 2025) — filtra por columna published")
    parser.add_argument("--batch-size", type=int, default=128,
                        help="Chunks por lote Voyage AI (default: 128; max permitido por API)")
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
