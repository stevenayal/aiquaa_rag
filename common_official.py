"""
common_official.py — helpers para scrapers/indexers de fuentes oficiales.
"""

import io
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import warnings

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

import pdfplumber
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import Client, create_client

for _env in [Path(__file__).parent / ".env", Path(__file__).parent / "BCP" / ".env", Path(__file__).parent / "CONATEL" / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

log = logging.getLogger(__name__)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
VOYAGE_MODEL = "voyage-3"
VOYAGE_BATCH = 8
EMBED_DELAY = 0.5

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,text/html,*/*",
    "Accept-Language": "es-PY,es;q=0.9",
}


@dataclass
class DocumentRecord:
    url: str
    category: str
    source: str
    title: str = ""
    published: Optional[str] = None
    filename: str = ""


def _parse_date(text: str) -> Optional[str]:
    patterns = [
        r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})",
        r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        g = m.groups()
        if len(g[0]) == 4:
            y, mo, d = int(g[0]), int(g[1]), int(g[2])
        else:
            d, mo, yy = g
            y = int(yy)
            if len(yy) == 2:
                y = 2000 + y
            d, mo = int(d), int(mo)
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            continue
    return None


def _filename_from_url(url: str) -> str:
    part = urlparse(url).path.split("/")[-1]
    part = part.split("?")[0].strip()
    return part[:200]


def _soup(url: str, verify: bool = True) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=45, verify=verify)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning(f"No se pudo cargar {url}: {e}")
        return None


def _extract_records_from_page(soup: BeautifulSoup, source: str, category: str, page_title: str, page_url: str, allowed_domains: list[str]) -> list[DocumentRecord]:
    records: list[DocumentRecord] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        full = urljoin(page_url, href)
        low = full.lower()
        if ".pdf" not in low:
            continue
        netloc = urlparse(full).netloc.lower()
        if allowed_domains and not any(d in netloc for d in allowed_domains):
            continue
        if full in seen:
            continue
        seen.add(full)
        link_text = a.get_text(" ", strip=True)
        title = link_text or page_title or _filename_from_url(full)
        published = _parse_date(f"{page_title} {link_text} {full}")
        records.append(
            DocumentRecord(
                url=full,
                category=category,
                source=source,
                title=title[:300],
                published=published,
                filename=_filename_from_url(full),
            )
        )
    return records


def run_official_scraper(source: str, sections: list[dict]) -> list[DocumentRecord]:
    all_records: list[DocumentRecord] = []
    seen_urls: set[str] = set()
    for section in sections:
        category = section["category"]
        index_url = section["index_url"]
        allowed_domains = section.get("allowed_domains", [])
        verify_ssl = section.get("verify_ssl", True)
        max_pages = section.get("max_pages", 1)
        page_param = section.get("page_param", "page")
        log.info(f"[{source}:{category}] {index_url}")
        for page in range(1, max_pages + 1):
            page_url = index_url if page == 1 else f"{index_url}{'&' if '?' in index_url else '?'}{page_param}={page}"
            soup = _soup(page_url, verify=verify_ssl)
            if not soup:
                break
            page_title = soup.title.get_text(strip=True) if soup.title else ""
            records = _extract_records_from_page(
                soup,
                source=source,
                category=category,
                page_title=page_title,
                page_url=page_url,
                allowed_domains=allowed_domains,
            )
            if not records and page > 1:
                break
            new_count = 0
            for r in records:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                all_records.append(r)
                new_count += 1
            log.info(f"  pagina={page} nuevos={new_count}")
            time.sleep(0.5)
    log.info(f"Total {source}: {len(all_records)} PDFs únicos")
    return all_records


def get_supabase() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def get_voyage():
    import voyageai

    return voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY", ""))


def download_pdf(url: str, verify_ssl: bool = True, timeout: int = 45) -> Optional[bytes]:
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True, verify=verify_ssl)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.error(f"Error descargando {url}: {e}")
        return None


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text_parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text(x_tolerance=2, y_tolerance=2)
                if t:
                    text_parts.append(f"[Pagina {i + 1}]\n{t.strip()}")
    except Exception as e:
        log.error(f"Error extrayendo texto PDF: {e}")
    return "\n\n".join(text_parts)


def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    if not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[dict] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        plen = len(para)
        if current_len + plen > chunk_size and current:
            content = "\n\n".join(current)
            chunks.append({"content": content, "chunk_index": len(chunks), "token_count": len(content) // 4})
            ov = content[-overlap:] if len(content) > overlap else content
            current, current_len = [ov, para], len(ov) + plen
        else:
            current.append(para)
            current_len += plen
    if current:
        content = "\n\n".join(current)
        if content.strip():
            chunks.append({"content": content, "chunk_index": len(chunks), "token_count": len(content) // 4})
    return chunks


def embed_chunks(voyage, texts: list[str], batch_size: int = VOYAGE_BATCH) -> list[list[float]]:
    all_emb: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            result = voyage.embed(batch, model=VOYAGE_MODEL, input_type="document")
            all_emb.extend(result.embeddings)
        except Exception as e:
            log.error(f"Error embedding lote {i // batch_size + 1}: {e}")
            all_emb.extend([[0.0] * 1024] * len(batch))
        time.sleep(EMBED_DELAY)
    return all_emb


def upsert_document(sb: Client, record: DocumentRecord) -> Optional[str]:
    data = {
        "source": record.source,
        "url": record.url,
        "title": record.title,
        "category": record.category,
        "published": record.published,
        "filename": record.filename,
    }
    try:
        res = sb.table("rag_documents").upsert(data, on_conflict="url").execute()
        return res.data[0]["id"]
    except Exception as e:
        log.error(f"Error upsert {record.url}: {e}")
        return None


def insert_chunks(sb: Client, document_id: str, chunks: list[dict], embeddings: Optional[list[list[float]]] = None) -> bool:
    rows = []
    for i, chunk in enumerate(chunks):
        row = {
            "document_id": document_id,
            "chunk_index": chunk["chunk_index"],
            "content": chunk["content"],
            "token_count": chunk["token_count"],
            "metadata": {},
        }
        if embeddings is not None:
            row["embedding"] = embeddings[i]
        rows.append(row)
    try:
        sb.table("rag_chunks").insert(rows).execute()
        return True
    except Exception as e:
        log.error(f"Error insertando chunks doc {document_id}: {e}")
        return False


def mark_document_indexed(sb: Client, document_id: str, error: Optional[str] = None):
    from datetime import timezone

    upd = {"indexed_at": datetime.now(timezone.utc).isoformat()}
    if error:
        upd["error"] = error[:500]
    sb.table("rag_documents").update(upd).eq("id", document_id).execute()


def delete_existing_chunks(sb: Client, document_id: str):
    sb.table("rag_chunks").delete().eq("document_id", document_id).execute()


def index_document(sb: Client, record: DocumentRecord, reindex: bool = False, no_embed: bool = False, voyage=None, verify_ssl: bool = True) -> bool:
    doc_id = upsert_document(sb, record)
    if not doc_id:
        return False
    if reindex:
        delete_existing_chunks(sb, doc_id)

    pdf_bytes = download_pdf(record.url, verify_ssl=verify_ssl)
    if not pdf_bytes:
        mark_document_indexed(sb, doc_id, error="No se pudo descargar PDF")
        return False

    text = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        mark_document_indexed(sb, doc_id, error="No se extrajo texto")
        return False

    chunks = split_into_chunks(text)
    if not chunks:
        mark_document_indexed(sb, doc_id, error="Sin chunks")
        return False

    if no_embed:
        ok = insert_chunks(sb, doc_id, chunks, embeddings=None)
    else:
        if voyage is None:
            voyage = get_voyage()
        embs = embed_chunks(voyage, [c["content"] for c in chunks])
        ok = insert_chunks(sb, doc_id, chunks, embeddings=embs)

    mark_document_indexed(sb, doc_id, error=None if ok else "Error insertando chunks")
    return ok


def run_indexer_for_source(source: str, scraper_fn, categories: Optional[list[str]] = None, reindex: bool = False, limit: Optional[int] = None, no_embed: bool = False, verify_ssl: bool = True):
    sb = get_supabase()
    voyage = None if no_embed else get_voyage()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    mode = "sin embeddings" if no_embed else "con embeddings"
    log.info(f"=== Scraping {source.upper()} [{mode}] ===")
    records = scraper_fn(categories=categories)

    if limit:
        records = records[:limit]
        log.info(f"Limitando a {limit} documentos")

    ok_count = fail_count = 0
    for i, record in enumerate(records, 1):
        log.info(f"[{i}/{len(records)}] {record.category} | {record.title[:80]}")
        success = index_document(sb, record, reindex=reindex, no_embed=no_embed, voyage=voyage, verify_ssl=verify_ssl)
        if success:
            ok_count += 1
        else:
            fail_count += 1
        time.sleep(0.3)

    log.info(f"=== Indexacion {source.upper()} completa ===")
    log.info(f"  Exitosos: {ok_count}")
    log.info(f"  Fallidos: {fail_count}")
    log.info(f"  Total: {len(records)}")
    if no_embed:
        log.info(f"  Embeddings pendientes. Correr: python re_embedder.py --source {source}")
