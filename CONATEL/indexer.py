"""
indexer.py — Pipeline de indexación RAG para regulaciones CONATEL

Modos:
  Normal  : scraping → PDF → chunks → embeddings → Supabase
  --no-embed : scraping → PDF → chunks → Supabase (sin embeddings)
               Útil para pre-poblar la DB; correr re_embedder.py después.
"""

import io
import logging
import os
import sys
import time
from typing import Optional

import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Fix SSL en Windows: usar certificados del sistema
try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

import pdfplumber
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

sys.path.insert(0, os.path.dirname(__file__))
from scraper import DocumentRecord, run_scraper

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────

SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_SERVICE_KEY"]

CHUNK_SIZE    = 800
CHUNK_OVERLAP = 150

VOYAGE_MODEL  = "voyage-3"
VOYAGE_BATCH  = 8
EMBED_DELAY   = 0.5

HEADERS = {
    "User-Agent": "ConatelRagIndexer/1.0 (+https://aiquaa.com)",
    "Accept": "application/pdf,*/*",
}


# ── Clientes ───────────────────────────────────────────────────────────────────

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_voyage():
    import voyageai
    api_key = os.environ.get("VOYAGE_API_KEY", "")
    return voyageai.Client(api_key=api_key)


# ── PDF ────────────────────────────────────────────────────────────────────────

def download_pdf(url: str, timeout: int = 30) -> Optional[bytes]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True, verify=False)
        r.raise_for_status()
        return r.content
    except requests.RequestException as e:
        log.error(f"Error descargando {url}: {e}")
        return None


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text(x_tolerance=2, y_tolerance=2)
                if t:
                    text_parts.append(f"[Página {i+1}]\n{t.strip()}")
    except Exception as e:
        log.error(f"Error extrayendo texto: {e}")
    return "\n\n".join(text_parts)


# ── Chunking ───────────────────────────────────────────────────────────────────

def split_into_chunks(text: str,
                      chunk_size: int = CHUNK_SIZE,
                      overlap: int = CHUNK_OVERLAP) -> list[dict]:
    if not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[dict] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        plen = len(para)
        if plen > chunk_size:
            if current:
                content = "\n\n".join(current)
                chunks.append({"content": content, "chunk_index": len(chunks),
                               "token_count": len(content) // 4})
                ov = content[-overlap:] if len(content) > overlap else content
                current, current_len = [ov], len(ov)
            words, sub, sub_len = para.split(), [], 0
            for w in words:
                sub.append(w); sub_len += len(w) + 1
                if sub_len >= chunk_size:
                    content = " ".join(sub)
                    chunks.append({"content": content, "chunk_index": len(chunks),
                                   "token_count": len(content) // 4})
                    sub = sub[-(overlap // 5):]; sub_len = sum(len(x)+1 for x in sub)
            if sub:
                current, current_len = [" ".join(sub)], sub_len
            continue
        if current_len + plen > chunk_size and current:
            content = "\n\n".join(current)
            chunks.append({"content": content, "chunk_index": len(chunks),
                           "token_count": len(content) // 4})
            ov = content[-overlap:] if len(content) > overlap else content
            current, current_len = [ov, para], len(ov) + plen
        else:
            current.append(para); current_len += plen

    if current:
        content = "\n\n".join(current)
        if content.strip():
            chunks.append({"content": content, "chunk_index": len(chunks),
                           "token_count": len(content) // 4})
    return chunks


# ── Embeddings (opcional) ──────────────────────────────────────────────────────

def embed_chunks(voyage, texts: list[str],
                 batch_size: int = VOYAGE_BATCH) -> list[list[float]]:
    all_emb: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        log.info(f"  Embedding lote {i//batch_size+1} ({len(batch)} chunks)...")
        try:
            result = voyage.embed(batch, model=VOYAGE_MODEL, input_type="document")
            all_emb.extend(result.embeddings)
        except Exception as e:
            log.error(f"  Error embedding lote {i}: {e}")
            all_emb.extend([[0.0] * 1024] * len(batch))
        time.sleep(EMBED_DELAY)
    return all_emb


# ── Supabase ───────────────────────────────────────────────────────────────────

def upsert_document(sb: Client, record: DocumentRecord) -> Optional[str]:
    data = {
        "source":    record.source,
        "url":       record.url,
        "title":     record.title,
        "category":  record.category,
        "published": record.published,
        "filename":  record.filename,
    }
    try:
        res = sb.table("rag_documents").upsert(data, on_conflict="url").execute()
        return res.data[0]["id"]
    except Exception as e:
        log.error(f"Error upsert {record.url}: {e}")
        return None


def insert_chunks(sb: Client, document_id: str,
                  chunks: list[dict],
                  embeddings: Optional[list[list[float]]] = None) -> bool:
    """
    Inserta chunks en rag_chunks.
    Si embeddings=None, guarda con embedding NULL (para re-embed posterior).
    """
    rows = []
    for idx, chunk in enumerate(chunks):
        row: dict = {
            "document_id": document_id,
            "chunk_index": chunk["chunk_index"],
            "content":     chunk["content"],
            "token_count": chunk["token_count"],
            "metadata":    {},
        }
        if embeddings is not None:
            row["embedding"] = embeddings[idx]
        rows.append(row)
    try:
        sb.table("rag_chunks").insert(rows).execute()
        return True
    except Exception as e:
        log.error(f"Error insertando chunks doc {document_id}: {e}")
        return False


def mark_document_indexed(sb: Client, document_id: str,
                          error: Optional[str] = None):
    from datetime import datetime, timezone
    upd: dict = {"indexed_at": datetime.now(timezone.utc).isoformat()}
    if error:
        upd["error"] = error[:500]
    sb.table("rag_documents").update(upd).eq("id", document_id).execute()


def delete_existing_chunks(sb: Client, document_id: str):
    sb.table("rag_chunks").delete().eq("document_id", document_id).execute()


# ── Pipeline ───────────────────────────────────────────────────────────────────

def index_document(sb: Client,
                   record: DocumentRecord,
                   reindex: bool = False,
                   no_embed: bool = False,
                   voyage=None) -> bool:
    """
    Indexa un documento.

    Args:
        no_embed: si True, guarda chunks sin embeddings (más rápido, sin API key Voyage)
        voyage:   cliente Voyage AI (ignorado si no_embed=True)
    """
    log.info(f"Indexando: {record.filename} [{record.category}]")

    doc_id = upsert_document(sb, record)
    if not doc_id:
        return False

    if not reindex:
        res = sb.table("rag_documents").select("indexed_at").eq("id", doc_id).execute()
        if res.data and res.data[0].get("indexed_at"):
            log.info("  → Ya indexado, saltando.")
            return True

    if reindex:
        delete_existing_chunks(sb, doc_id)

    pdf_bytes = download_pdf(record.url)
    if not pdf_bytes:
        mark_document_indexed(sb, doc_id, error="Error descargando PDF")
        return False

    text = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        log.warning(f"  → PDF sin texto (escaneado?): {record.url}")
        mark_document_indexed(sb, doc_id, error="PDF sin texto extraíble")
        return False

    log.info(f"  → {len(text):,} chars | ", )

    chunks = split_into_chunks(text)
    if not chunks:
        mark_document_indexed(sb, doc_id, error="Sin chunks generados")
        return False

    log.info(f"  → {len(chunks)} chunks")

    if no_embed:
        ok = insert_chunks(sb, doc_id, chunks, embeddings=None)
    else:
        texts = [c["content"] for c in chunks]
        embeddings = embed_chunks(voyage, texts)
        ok = insert_chunks(sb, doc_id, chunks, embeddings=embeddings)

    mark_document_indexed(sb, doc_id, error=None if ok else "Error insertando chunks")
    log.info(f"  → {'✓ OK' if ok else '✗ Error'}")
    return ok


def run_indexer(
    categories: Optional[list[str]] = None,
    reindex: bool = False,
    limit: Optional[int] = None,
    no_embed: bool = False,
):
    sb = get_supabase()
    voyage = None if no_embed else get_voyage()

    mode = "sin embeddings" if no_embed else "con embeddings"
    log.info(f"=== Scraping CONATEL [{mode}] ===")
    records = run_scraper(categories=categories)

    if limit:
        records = records[:limit]
        log.info(f"Limitando a {limit} documentos")

    log.info(f"=== Indexando {len(records)} documentos ===")
    ok_count = fail_count = 0

    for i, record in enumerate(records, 1):
        log.info(f"[{i}/{len(records)}]")
        success = index_document(sb, record,
                                 reindex=reindex,
                                 no_embed=no_embed,
                                 voyage=voyage)
        if success:
            ok_count += 1
        else:
            fail_count += 1
        time.sleep(0.3)

    log.info("\n=== Indexación CONATEL completa ===")
    log.info(f"  ✓ Exitosos : {ok_count}")
    log.info(f"  ✗ Fallidos : {fail_count}")
    log.info(f"  Total      : {len(records)}")
    if no_embed:
        log.info("  → Embeddings pendientes. Correr: python re_embedder.py --source conatel")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Indexador RAG - CONATEL")
    parser.add_argument("--categories", nargs="+",
                        choices=["resolucion", "ley", "decreto", "reglamento"])
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-embed", action="store_true",
                        help="Guardar texto sin embeddings (más rápido, no necesita Voyage API key)")
    args = parser.parse_args()

    run_indexer(
        categories=args.categories,
        reindex=args.reindex,
        limit=args.limit,
        no_embed=args.no_embed,
    )
