"""
scraper.py — Scraper del sitio CONATEL (conatel.gov.py)

Estructura real del sitio:
  - Resoluciones: /resoluciones/ → páginas por año → posts individuales → PDF
  - Leyes:        /leyes/        → posts individuales → PDF
  - Decretos:     /decretos/     → posts individuales → PDF
  - Reglamentos:  /reglamentos/  → PDF(s) directos + posts → PDF

El sitio usa WordPress. Certificado SSL inválido → verify=False.
"""

import re
import time
import logging
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CONATEL_BASE = "https://www.conatel.gov.py"

# Secciones regulatorias del sitio CONATEL
# Cada sección tiene su estructura particular (ver SCRAPING_NOTES más abajo)
SECTIONS = [
    {
        "category": "resolucion",
        "label": "Resoluciones de Directorio",
        "index_url": f"{CONATEL_BASE}/resoluciones/",
        "mode": "year_index",   # index → year pages → posts → PDF
        # Patrones de URLs de páginas por año (el sitio no es consistente)
        "year_url_patterns": [
            "resoluciones-{year}",
            "resoluciones-ano-{year}",
        ],
        "year_range": range(2011, 2027),
    },
    {
        "category": "ley",
        "label": "Leyes de Telecomunicaciones",
        "index_url": f"{CONATEL_BASE}/leyes/",
        "mode": "flat_listing",  # index → posts → PDF
    },
    {
        "category": "decreto",
        "label": "Decretos",
        "index_url": f"{CONATEL_BASE}/decretos/",
        "mode": "flat_listing",
    },
    {
        "category": "reglamento",
        "label": "Reglamentos",
        "index_url": f"{CONATEL_BASE}/reglamentos/",
        "mode": "flat_listing",  # mezcla: posts + PDFs directos
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ConatelRagBot/1.0; "
        "+https://aiquaa.com)"
    ),
    "Accept-Language": "es-PY,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

DATE_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b")


# ── Tipos ─────────────────────────────────────────────────────────────────────

@dataclass
class DocumentRecord:
    url: str
    category: str
    source: str = "conatel"
    title: str = ""
    published: Optional[str] = None
    filename: str = ""


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3, delay: float = 2.0) -> Optional[requests.Response]:
    """GET con reintentos, backoff y SSL verify=False."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25, verify=False)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log.warning(f"Intento {attempt+1}/{retries} para {url}: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return None


def _soup(url: str) -> Optional[BeautifulSoup]:
    """Descarga y parsea. Retorna None si falla."""
    resp = _get(url)
    if not resp:
        return None
    return BeautifulSoup(resp.text, "html.parser")


# ── Utilidades ─────────────────────────────────────────────────────────────────

def _parse_date(text: str) -> Optional[str]:
    """Extrae fecha DD/MM/YYYY o YYYY-MM-DD del texto."""
    m = DATE_RE.search(text)
    if m:
        d, mo, y = m.groups()
        try:
            return datetime(int(y), int(mo), int(d)).date().isoformat()
        except ValueError:
            pass
    # ISO date
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).date().isoformat()
        except ValueError:
            pass
    return None


def _clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Elimina header/nav/footer/scripts del soup para limpiar links espurios.
    Preserva navs de paginación (class con 'navigation' o 'pagination').
    """
    for tag in soup.find_all(["header", "script", "style"]):
        tag.decompose()
    # Solo remover <nav> que NO sean de paginación
    for tag in soup.find_all("nav"):
        classes = " ".join(tag.get("class", []))
        if "navigation" not in classes and "pagination" not in classes:
            tag.decompose()
    # Footer siempre
    for tag in soup.find_all("footer"):
        tag.decompose()
    return soup


def _extract_pdf_links_from_page(soup: BeautifulSoup, category: str) -> list[DocumentRecord]:
    """Extrae PDFs directos de una página (sin visitar sub-posts)."""
    records = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href.lower().endswith(".pdf"):
            continue
        if "conatel.gov.py" not in urlparse(href).netloc:
            continue
        if href in seen:
            continue
        seen.add(href)

        title = a.get_text(strip=True)
        if not title:
            parent = a.find_parent(["td", "li", "p", "div"])
            title = (parent.get_text(strip=True)[:200] if parent else "") or href.split("/")[-1]

        filename = href.split("/")[-1].split("?")[0]

        # Fecha: buscar en el contexto cercano
        row = a.find_parent("tr")
        published = None
        if row:
            published = _parse_date(row.get_text())
        if not published:
            published = _parse_date(href)  # a veces el año está en la URL

        records.append(DocumentRecord(
            url=href,
            category=category,
            source="conatel",
            title=title,
            published=published,
            filename=filename,
        ))

    return records


def _post_links_from_listing(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Extrae (title, url) de posts en una página de listado WordPress.
    Busca el patrón: <h2 class="entry-title"><a href=...> o similar.
    """
    posts: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Patrón WordPress estándar: h2.entry-title > a
    for h in soup.find_all(["h1", "h2", "h3"]):
        a = h.find("a", href=True)
        if a:
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if (CONATEL_BASE in href and
                    href not in seen and
                    "wp-content" not in href and
                    "#" not in href):
                seen.add(href)
                posts.append((text, href))

    # Fallback: links "Leer más" / "Descargar"
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text(strip=True).lower()
        if (text in ("leer más »", "leer más", "descargar") and
                CONATEL_BASE in href and
                href not in seen and
                "wp-content" not in href):
            seen.add(href)
            posts.append((a.get_text(strip=True), href))

    return posts


def _scrape_post(url: str, category: str, fallback_title: str = "") -> list[DocumentRecord]:
    """
    Visita un post individual y extrae los PDFs adjuntos.
    """
    soup = _soup(url)
    if not soup:
        return []

    # Limpiar elementos globales (header/nav/footer) para evitar PDFs espurios
    _clean_soup(soup)

    # Título del post
    h1 = soup.find("h1")
    title = (h1.get_text(strip=True) if h1 else fallback_title) or url.split("/")[-2]

    # Fecha de publicación (meta WordPress)
    published = None
    meta = soup.find("meta", {"property": "article:published_time"})
    if meta and meta.get("content"):
        published = _parse_date(meta["content"])
    if not published:
        time_tag = soup.find("time")
        if time_tag:
            published = _parse_date(
                time_tag.get("datetime", "") or time_tag.get_text()
            )
    if not published:
        published = _parse_date(url)

    records: list[DocumentRecord] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href.lower().endswith(".pdf"):
            continue
        if "conatel.gov.py" not in urlparse(href).netloc:
            continue
        if href in seen:
            continue
        seen.add(href)

        link_text = a.get_text(strip=True)
        doc_title = title
        if link_text and link_text.lower() not in ("descargar", "descargar - resolución",
                                                     "descargar - reglamento", "aquí", "here"):
            doc_title = f"{title} — {link_text}"

        records.append(DocumentRecord(
            url=href,
            category=category,
            source="conatel",
            title=doc_title[:300],
            published=published,
            filename=href.split("/")[-1].split("?")[0],
        ))

    return records


# ── Scrapers por modo ─────────────────────────────────────────────────────────

def scrape_flat_listing(section: dict) -> list[DocumentRecord]:
    """
    Scrapea secciones con listado plano: index → posts → PDF.
    Soporta paginación WordPress (?paged=N).
    """
    category = section["category"]
    index_url = section["index_url"]
    all_records: list[DocumentRecord] = []
    seen_urls: set[str] = set()

    url: Optional[str] = index_url
    page_num = 0

    while url:
        page_num += 1
        log.info(f"[{category}] Listado página {page_num}: {url}")
        soup = _soup(url)
        if not soup:
            break

        _clean_soup(soup)

        # 1. PDFs directos en el listado
        direct = _extract_pdf_links_from_page(soup, category)
        for r in direct:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                all_records.append(r)
                log.info(f"  PDF directo: {r.filename}")

        # 2. Posts con "Leer más"
        posts = _post_links_from_listing(soup)
        log.info(f"  → {len(posts)} posts encontrados en esta página")

        for title, post_url in posts:
            if post_url in seen_urls:
                continue
            seen_urls.add(post_url)
            log.info(f"  Visitando: {post_url}")
            records = _scrape_post(post_url, category, fallback_title=title)
            for r in records:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_records.append(r)
                    log.info(f"    → PDF: {r.filename}")
            time.sleep(0.8)

        # Paginación
        next_url = _get_next_page(soup, url)
        url = next_url if next_url and next_url != url else None
        if url:
            time.sleep(1.5)

    return all_records


def scrape_year_index(section: dict) -> list[DocumentRecord]:
    """
    Scrapea resoluciones organizadas por año.
    /resoluciones/ → año links → listado de posts → post → PDF
    """
    category = section["category"]
    index_url = section["index_url"]
    all_records: list[DocumentRecord] = []
    seen_urls: set[str] = set()

    log.info(f"[{category}] Cargando índice de años: {index_url}")
    soup = _soup(index_url)
    if not soup:
        return []

    # Extraer links a páginas de año del índice
    year_pages: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if CONATEL_BASE not in href:
            continue
        text = a.get_text(strip=True)
        # Links tipo "RESOLUCIONES AÑO 2025"
        if re.search(r"resoluci[oó]n.*\d{4}|resolucion.*\d{4}|\d{4}.*resoluci", text.lower()):
            if href not in year_pages:
                year_pages.append(href)

    # Fallback: construir URLs por año si no se encontraron
    if not year_pages:
        log.info("  No se encontraron links de año en el índice; construyendo por patrón")
        for year in section.get("year_range", range(2015, 2027)):
            for pattern in section.get("year_url_patterns", []):
                candidate = f"{CONATEL_BASE}/{pattern.format(year=year)}/"
                year_pages.append(candidate)

    log.info(f"  Páginas de año encontradas: {len(year_pages)}")

    for year_url in year_pages:
        log.info(f"[{category}] Año: {year_url}")

        # Paginar dentro de cada página de año (/resoluciones-2022/2/, /3/, ...)
        page_url: Optional[str] = year_url
        year_page_num = 0

        while page_url:
            year_page_num += 1
            year_soup = _soup(page_url)
            if not year_soup:
                log.warning(f"  → No accesible: {page_url}")
                break

            _clean_soup(year_soup)
            posts = _post_links_from_listing(year_soup)
            log.info(f"  → Página {year_page_num}: {len(posts)} resoluciones")

            for title, post_url in posts:
                if post_url in seen_urls:
                    continue
                seen_urls.add(post_url)
                records = _scrape_post(post_url, category, fallback_title=title)
                for r in records:
                    if r.url not in seen_urls:
                        seen_urls.add(r.url)
                        all_records.append(r)
                time.sleep(0.8)

            next_p = _get_next_page(year_soup, page_url)
            page_url = next_p if next_p and next_p != page_url else None
            if page_url:
                time.sleep(1.0)

        time.sleep(0.5)

    return all_records


def _get_next_page(soup: BeautifulSoup, current_url: str) -> Optional[str]:
    """
    Detecta link a la página siguiente (WordPress).
    Busca en este orden:
      1. <link rel="next"> en el head
      2. <a rel="next"> explícito
      3. Link "Siguiente" DENTRO de un nav/div de paginación
    Evita confundir "Leer más »" con la paginación.
    """
    # 1. <link rel="next" href="..."> en el <head>
    link_tag = soup.find("link", rel=lambda v: v and "next" in (v if isinstance(v, list) else [v]))
    if link_tag and link_tag.get("href"):
        return urljoin(current_url, link_tag["href"])

    # 2. <a rel="next">
    a_tag = soup.find("a", rel=lambda v: v and "next" in (v if isinstance(v, list) else [v]))
    if a_tag and a_tag.get("href"):
        return urljoin(current_url, a_tag["href"])

    # 3. "Siguiente" dentro de contenedores de paginación
    #    Nota: usar class_=lambda (no attrs={'class': lambda}) por comportamiento de BS4
    pag_containers = soup.find_all(
        class_=lambda c: c and any(
            kw in (" ".join(c) if isinstance(c, list) else str(c))
            for kw in ("pagination", "navigation", "nav-links", "page-navigation")
        )
    )
    for container in pag_containers:
        for a in container.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if "siguiente" in text or text in ("next", ">", "»", "›"):
                href = urljoin(current_url, a["href"])
                if href != current_url:
                    return href

    return None


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run_scraper(
    categories: Optional[list[str]] = None,
) -> list[DocumentRecord]:
    """
    Scraper principal de CONATEL.

    Args:
        categories: lista de categorías. None = todas.
            Opciones: 'resolucion', 'ley', 'decreto', 'reglamento'

    Returns:
        Lista de DocumentRecord únicos por URL.
    """
    sections = SECTIONS
    if categories:
        sections = [s for s in SECTIONS if s["category"] in categories]

    seen_urls: set[str] = set()
    all_records: list[DocumentRecord] = []

    for section in sections:
        log.info(f"\n{'='*60}")
        log.info(f"=== Scrapeando CONATEL: {section['label']} ===")
        log.info(f"{'='*60}")

        mode = section.get("mode", "flat_listing")
        if mode == "year_index":
            records = scrape_year_index(section)
        else:
            records = scrape_flat_listing(section)

        for r in records:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                all_records.append(r)

        log.info(f"  Subtotal [{section['category']}]: {len(records)} PDFs")

    log.info(f"\nTotal PDFs únicos CONATEL: {len(all_records)}")
    return all_records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper CONATEL")
    parser.add_argument(
        "--categories", nargs="+",
        choices=["resolucion", "ley", "decreto", "reglamento"],
        help="Categorías (default: todas)",
    )
    args = parser.parse_args()

    records = run_scraper(categories=args.categories)
    print(f"\n{'='*60}")
    print(f"Total: {len(records)} PDFs")
    for r in records[:20]:
        print(f"  [{r.category}] {r.title[:60]} | {r.published or 'sin fecha'}")
        print(f"           {r.url}")
