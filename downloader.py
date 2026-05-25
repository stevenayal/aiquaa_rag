"""
downloader.py — Descarga todos los PDFs de BCP y CONATEL a disco local.

Organización:
  downloads/
    bcp/
      resolucion/
      circular/
      reglamento/
      norma_prudencial/
    conatel/
      resolucion/
      ley/
      decreto/
      reglamento/

Fuentes de URLs:
  1. Supabase rag_documents (todos los ya indexados)
  2. BCP/data/vigentes.json (fallback para BCP no-yet-in-DB)

Uso:
  python downloader.py                    # descarga todo
  python downloader.py --source bcp       # solo BCP
  python downloader.py --source conatel   # solo CONATEL
  python downloader.py --workers 4        # descargas paralelas (default: 3)
  python downloader.py --dry-run          # solo cuenta, no descarga
"""

import argparse
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

import requests
from dotenv import load_dotenv
from supabase import create_client

# Carga .env desde root, BCP/ o CONATEL/ (donde exista)
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

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BASE_DIR     = Path(__file__).parent / "downloads"
BCP_SEED     = Path(__file__).parent / "BCP" / "data" / "vigentes.json"

HEADERS_BCP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
    "Accept-Language": "es-PY,es;q=0.9",
}
HEADERS_CONATEL = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_filename(url: str, title: str, filename: str) -> str:
    """Deriva un nombre de archivo limpio para el PDF."""
    # Preferir filename del DB si existe y parece un PDF
    if filename and filename.lower().endswith(".pdf"):
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
        return clean[:180] + ".pdf" if not clean.endswith(".pdf") else clean[:180]

    # Intentar extraer del path de la URL
    path = url.split("?")[0].rstrip("/")
    parts = path.split("/")
    for part in reversed(parts):
        decoded = unquote(part).replace("+", " ")
        if decoded.lower().endswith(".pdf"):
            clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", decoded)
            return clean[:180]

    # Fallback: slug del título
    slug = re.sub(r'[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\s]', '', title)[:60].strip()
    slug = re.sub(r'\s+', '_', slug)
    return slug + ".pdf" if slug else "documento.pdf"


def download_one(doc: dict) -> dict:
    """
    Descarga un PDF. Retorna dict con resultado.
    doc: {url, title, category, source, filename}
    """
    url      = doc["url"]
    source   = doc["source"]
    category = doc.get("category", "sin_categoria")
    title    = doc.get("title", "")
    filename = doc.get("filename", "")

    dest_dir = BASE_DIR / source / category
    dest_dir.mkdir(parents=True, exist_ok=True)

    fname = safe_filename(url, title, filename)
    dest  = dest_dir / fname

    # Skip si ya existe y tiene contenido
    if dest.exists() and dest.stat().st_size > 1024:
        return {"url": url, "path": str(dest), "status": "skip", "size": dest.stat().st_size}

    headers = HEADERS_BCP if source == "bcp" else HEADERS_CONATEL
    verify  = False if source == "conatel" else True

    try:
        r = requests.get(url, headers=headers, timeout=60,
                         allow_redirects=True, verify=verify, stream=True)
        r.raise_for_status()

        # Verificar que es un PDF
        ct = r.headers.get("Content-Type", "")
        if "pdf" not in ct.lower() and not url.lower().endswith(".pdf"):
            # Intentar igualmente si el body empieza con %PDF
            content = r.content
            if not content.startswith(b"%PDF"):
                return {"url": url, "path": None, "status": "not_pdf", "size": 0}
        else:
            content = r.content

        # Evitar archivos vacíos o muy pequeños
        if len(content) < 500:
            return {"url": url, "path": None, "status": "too_small", "size": len(content)}

        # Manejar colisión de nombres
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        dest.write_bytes(content)
        return {"url": url, "path": str(dest), "status": "ok", "size": len(content)}

    except requests.RequestException as e:
        return {"url": url, "path": None, "status": "error", "error": str(e)[:200], "size": 0}


# ── Fuentes de documentos ──────────────────────────────────────────────────────

def get_docs_from_supabase(source: Optional[str] = None) -> list[dict]:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    query = sb.table("rag_documents").select("url,title,category,source,filename")
    if source:
        query = query.eq("source", source)
    # Paginar de 1000 en 1000
    all_docs = []
    offset = 0
    while True:
        res = query.range(offset, offset + 999).execute()
        if not res.data:
            break
        all_docs.extend(res.data)
        if len(res.data) < 1000:
            break
        offset += 1000
    return all_docs


def get_docs_from_seed(seed_file: Path, existing_urls: set) -> list[dict]:
    """Lee vigentes.json de BCP para docs que aún no están en Supabase."""
    if not seed_file.exists():
        return []
    with open(seed_file, encoding="utf-8") as f:
        data = json.load(f)
    extra = []
    for d in data:
        url = d.get("url", "")
        if url and url not in existing_urls:
            extra.append({
                "url":      url,
                "title":    d.get("title", ""),
                "category": d.get("category", "resolucion"),
                "source":   "bcp",
                "filename": d.get("filename", ""),
            })
    return extra


# ── Runner ─────────────────────────────────────────────────────────────────────

def run_downloader(
    source: Optional[str] = None,
    workers: int = 3,
    dry_run: bool = False,
):
    log.info("=== Descargador de PDFs RAG ===")

    # 1. Obtener docs de Supabase
    log.info("Leyendo Supabase...")
    docs = get_docs_from_supabase(source)
    log.info(f"  {len(docs)} docs en Supabase")

    # 2. Complementar BCP con seed local (para docs no-yet-indexed)
    if source in (None, "bcp"):
        existing = {d["url"] for d in docs}
        extra = get_docs_from_seed(BCP_SEED, existing)
        if extra:
            log.info(f"  +{len(extra)} docs BCP del seed local (no en Supabase aún)")
            docs.extend(extra)

    # 3. Deduplicar por URL
    seen: set = set()
    unique_docs = []
    for d in docs:
        url = d.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique_docs.append(d)
    docs = unique_docs

    # Resumen por fuente
    from collections import Counter
    by_source = Counter(d["source"] for d in docs)
    for src, cnt in sorted(by_source.items()):
        log.info(f"  {src}: {cnt} docs")
    log.info(f"  TOTAL: {len(docs)} docs únicos")

    if dry_run:
        log.info("Modo dry-run — no se descarga nada.")
        by_cat = Counter(f"{d['source']}/{d['category']}" for d in docs)
        for k, v in sorted(by_cat.items()):
            log.info(f"  {k}: {v}")
        return

    BASE_DIR.mkdir(parents=True, exist_ok=True)

    # 4. Descargar en paralelo
    log.info(f"\nDescargando con {workers} workers → {BASE_DIR}")
    ok = skip = fail = 0
    total_bytes = 0
    errors = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, d): d for d in docs}
        done = 0
        for fut in as_completed(futures):
            done += 1
            res = fut.result()
            status = res["status"]

            if status == "ok":
                ok += 1
                total_bytes += res["size"]
                if ok % 20 == 0 or done % 50 == 0:
                    log.info(f"  [{done}/{len(docs)}] ✓ {ok} descargados, "
                             f"{skip} skip, {fail} errores "
                             f"({total_bytes/1_048_576:.1f} MB)")
            elif status == "skip":
                skip += 1
                total_bytes += res["size"]
            else:
                fail += 1
                errors.append(res)
                log.warning(f"  ✗ {res['url'][:70]} → {status}: {res.get('error','')[:80]}")

    log.info(f"\n=== Descarga completa ===")
    log.info(f"  ✓ Descargados  : {ok}")
    log.info(f"  → Ya existían  : {skip}")
    log.info(f"  ✗ Errores      : {fail}")
    log.info(f"  Total en disco : {total_bytes/1_048_576:.1f} MB")
    log.info(f"  Carpeta        : {BASE_DIR.resolve()}")

    # Guardar log de errores
    if errors:
        err_file = BASE_DIR / "errores.json"
        with open(err_file, "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        log.info(f"  Log errores    : {err_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descargador de PDFs RAG BCP/CONATEL")
    parser.add_argument("--source", choices=["bcp", "conatel"],
                        help="Fuente a descargar (default: ambas)")
    parser.add_argument("--workers", type=int, default=3,
                        help="Descargas en paralelo (default: 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo contar docs, no descargar")
    args = parser.parse_args()

    run_downloader(
        source=args.source,
        workers=args.workers,
        dry_run=args.dry_run,
    )
