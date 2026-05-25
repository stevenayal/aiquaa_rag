"""
ocr_processor.py — OCR pipeline: PDF → texto → chunks → Supabase.

Flujo por PDF:
  1. pdfplumber extrae texto nativo (rápido, gratis)
  2. Si texto < MIN_CHARS_NATIVE → PyMuPDF renderiza páginas a imagen
     → Tesseract OCR (spa+eng) → texto OCR
  3. Chunking igual que el indexer (800 chars, 150 overlap)
  4. Upsert chunks en rag_chunks con embedding=NULL (re_embedder.py después)

Uso:
  python ocr_processor.py                          # todos los PDFs en downloads/
  python ocr_processor.py --source bcp             # solo BCP
  python ocr_processor.py --source conatel         # solo CONATEL
  python ocr_processor.py --workers 2              # paralelo (default: 2; OCR es CPU-intensivo)
  python ocr_processor.py --dry-run                # contar sin procesar
  python ocr_processor.py --force                  # re-procesar aunque ya tengan chunks
  python ocr_processor.py --dpi 200               # resolución OCR (default: 200; 300 = mejor calidad)
"""

import argparse
import logging
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import warnings
warnings.filterwarnings("ignore")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

from dotenv import load_dotenv

# ── .env ───────────────────────────────────────────────────────────────────────
_root = Path(__file__).parent
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

SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_SERVICE_KEY"]
DOWNLOADS_DIR    = Path(__file__).parent / "downloads"
TESSERACT_CMD    = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_PREFIX  = str(Path.home() / "tessdata")

# OCR config
TESSERACT_LANG   = "spa+eng"      # Spanish primary, English fallback
DPI_DEFAULT      = 200            # 200 DPI = ~1650×2100 px for A4, fast enough
MIN_CHARS_NATIVE = 100            # below this → use OCR instead of pdfplumber

# Chunking (must match indexer)
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 150


# ── Text extraction ─────────────────────────────────────────────────────────────

def extract_native(pdf_path: Path) -> str:
    """Extract text with pdfplumber (native PDF text layer)."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
            return "\n".join(pages)
    except Exception:
        return ""


def extract_ocr(pdf_path: Path, dpi: int = DPI_DEFAULT) -> str:
    """Render each PDF page with PyMuPDF and run Tesseract."""
    import fitz          # PyMuPDF
    import pytesseract
    from PIL import Image
    import io

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    os.environ["TESSDATA_PREFIX"] = TESSDATA_PREFIX

    # TESSDATA_PREFIX env var is set above; don't duplicate in config string
    tess_config = "--oem 1 --psm 6"

    try:
        doc = fitz.open(str(pdf_path))
        pages_text = []
        mat = fitz.Matrix(dpi / 72, dpi / 72)   # 72 DPI is PDF default

        for page in doc:
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang=TESSERACT_LANG, config=tess_config)
            pages_text.append(text)

        doc.close()
        return "\n".join(pages_text)
    except Exception as e:
        return ""


def extract_text(pdf_path: Path, dpi: int = DPI_DEFAULT) -> tuple[str, str]:
    """
    Returns (text, method) where method is 'native' or 'ocr'.
    Tries native first; falls back to OCR if text is too short.
    """
    native = extract_native(pdf_path)
    if len(native.strip()) >= MIN_CHARS_NATIVE:
        return native, "native"
    ocr_text = extract_ocr(pdf_path, dpi)
    return ocr_text, "ocr"


# ── Chunker ────────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


# ── Supabase helpers ───────────────────────────────────────────────────────────

def _paginate(sb, table: str, select: str, filters: dict = None) -> list[dict]:
    """Paginate through a Supabase table, recreating query each page to avoid param accumulation."""
    all_rows = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        res = q.range(offset, offset + 999).execute()
        if not res.data:
            break
        all_rows.extend(res.data)
        if len(res.data) < 1000:
            break
        offset += 1000
    return all_rows


def get_doc_id_map(source: Optional[str] = None) -> list[dict]:
    """Return list of doc records from rag_documents."""
    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    filters = {"source": source} if source else {}
    return _paginate(sb, "rag_documents", "id,url,filename,source", filters)


def get_existing_chunk_doc_ids(source: Optional[str] = None) -> set[str]:
    """Return set of doc_ids that already have chunks in rag_chunks."""
    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    # For source filter: get doc_ids from rag_documents first, then check chunks
    if source:
        docs = get_doc_id_map(source)
        doc_ids = {d["id"] for d in docs}
    else:
        doc_ids = None

    all_rows = _paginate(sb, "rag_chunks", "document_id")
    result = {r["document_id"] for r in all_rows}
    if doc_ids is not None:
        result &= doc_ids   # intersect with source-specific doc_ids
    return result


def upsert_chunks(doc_id: str, chunks: list[str]) -> int:
    """Insert chunks into rag_chunks with NULL embedding. Returns inserted count."""
    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    rows = [
        {
            "document_id": doc_id,
            "chunk_index": i,
            "content":     chunk,
            "embedding":   None,
        }
        for i, chunk in enumerate(chunks)
    ]
    # Delete existing chunks for this doc first (re-process case)
    sb.table("rag_chunks").delete().eq("document_id", doc_id).execute()
    if rows:
        sb.table("rag_chunks").insert(rows).execute()
    return len(rows)


# ── Per-file worker (runs in subprocess for parallelism) ───────────────────────

def _process_one(args: tuple) -> dict:
    """Worker: extract text from one PDF and upsert chunks. Runs in subprocess."""
    pdf_path_str, doc_id, dpi = args
    pdf_path = Path(pdf_path_str)

    # Re-setup env in subprocess
    os.environ["TESSDATA_PREFIX"] = TESSDATA_PREFIX

    try:
        text, method = extract_text(pdf_path, dpi)
        if not text.strip():
            return {
                "file": pdf_path.name, "doc_id": doc_id,
                "status": "empty", "chunks": 0, "method": method,
            }
        chunks = chunk_text(text)
        inserted = upsert_chunks(doc_id, chunks)
        return {
            "file": pdf_path.name, "doc_id": doc_id,
            "status": "ok", "chunks": inserted, "method": method,
        }
    except Exception as e:
        return {
            "file": pdf_path.name, "doc_id": doc_id,
            "status": "error", "chunks": 0, "error": str(e)[:200], "method": "?",
        }


# ── Main runner ────────────────────────────────────────────────────────────────

def run_ocr(
    source: Optional[str] = None,
    workers: int = 2,
    dry_run: bool = False,
    force: bool = False,
    dpi: int = DPI_DEFAULT,
):
    log.info("=== OCR Processor (Tesseract local) ===")

    # 1. Get all docs from Supabase
    log.info("Leyendo rag_documents desde Supabase...")
    all_docs = get_doc_id_map(source)
    log.info(f"  {len(all_docs)} docs en Supabase")

    # 2. Build URL→id and filename→id maps
    url_to_id: dict[str, str] = {}
    fname_to_id: dict[str, str] = {}
    for doc in all_docs:
        url_to_id[doc["url"]] = doc["id"]
        if doc.get("filename"):
            stem = Path(doc["filename"]).stem.lower()
            fname_to_id[stem] = doc["id"]

    # 3. Find PDF files on disk
    sources_to_scan = [source] if source else ["bcp", "conatel"]
    pdf_files: list[Path] = []
    for src in sources_to_scan:
        src_dir = DOWNLOADS_DIR / src
        if src_dir.exists():
            pdf_files.extend(src_dir.rglob("*.pdf"))

    log.info(f"  {len(pdf_files)} PDFs en disco (downloads/)")

    # 4. Match PDFs to doc_ids
    matched: list[tuple[Path, str]] = []
    unmatched: list[Path] = []

    for pdf_path in pdf_files:
        doc_id = None
        # Try to match by filename stem (case-insensitive)
        stem = pdf_path.stem.lower()
        if stem in fname_to_id:
            doc_id = fname_to_id[stem]
        else:
            # Try substring match in URL
            name = pdf_path.name.lower()
            for url, uid in url_to_id.items():
                if name in url.lower() or url.lower().endswith(name):
                    doc_id = uid
                    break
        if doc_id:
            matched.append((pdf_path, doc_id))
        else:
            unmatched.append(pdf_path)

    log.info(f"  Matcheados: {len(matched)}, sin match en DB: {len(unmatched)}")

    # 5. Filter already-processed (unless --force)
    if not force:
        log.info("Verificando chunks existentes...")
        existing_ids = get_existing_chunk_doc_ids(source)
        before = len(matched)
        matched = [(p, d) for p, d in matched if d not in existing_ids]
        skipped = before - len(matched)
        log.info(f"  {skipped} ya tienen chunks → skip (usa --force para re-procesar)")

    log.info(f"  {len(matched)} PDFs a procesar")

    if dry_run:
        log.info("Modo dry-run — no se procesa nada.")
        return

    if not matched:
        log.info("Nada que procesar.")
        return

    # 6. Process in parallel
    log.info(f"\nProcesando con {workers} workers (DPI={dpi})...")
    ok = empty = fail = total_chunks = 0
    ocr_count = native_count = 0
    errors = []
    done = 0

    args_list = [(str(p), d, dpi) for p, d in matched]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process_one, a): a for a in args_list}
        for fut in as_completed(futures):
            done += 1
            res = fut.result()
            status = res["status"]
            method = res.get("method", "?")

            if status == "ok":
                ok += 1
                total_chunks += res["chunks"]
                if method == "ocr":
                    ocr_count += 1
                else:
                    native_count += 1
            elif status == "empty":
                empty += 1
            else:
                fail += 1
                errors.append(res)
                log.warning(f"  ✗ {res['file'][:60]} → {res.get('error','empty')[:80]}")

            if done % 10 == 0 or done == len(matched):
                log.info(
                    f"  [{done}/{len(matched)}] ✓ {ok} OK "
                    f"(native:{native_count} ocr:{ocr_count}) "
                    f"| vacíos:{empty} | errores:{fail} "
                    f"| chunks:{total_chunks}"
                )

    log.info(f"\n=== OCR completo ===")
    log.info(f"  ✓ Procesados   : {ok} ({native_count} nativos, {ocr_count} OCR)")
    log.info(f"  ∅ Texto vacío  : {empty}")
    log.info(f"  ✗ Errores      : {fail}")
    log.info(f"  Total chunks   : {total_chunks}")
    if errors:
        import json
        err_file = DOWNLOADS_DIR / "ocr_errores.json"
        with open(err_file, "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        log.info(f"  Log errores    : {err_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OCR de PDFs RAG con Tesseract")
    parser.add_argument("--source", choices=["bcp", "conatel"],
                        help="Fuente a procesar (default: ambas)")
    parser.add_argument("--workers", type=int, default=2,
                        help="Procesos paralelos (default: 2; OCR es CPU-intensivo)")
    parser.add_argument("--dpi", type=int, default=DPI_DEFAULT,
                        help=f"Resolución de renderizado PDF→imagen (default: {DPI_DEFAULT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo contar, no procesar")
    parser.add_argument("--force", action="store_true",
                        help="Re-procesar aunque ya tengan chunks")
    args = parser.parse_args()

    run_ocr(
        source=args.source,
        workers=args.workers,
        dry_run=args.dry_run,
        force=args.force,
        dpi=args.dpi,
    )
