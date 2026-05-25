"""
scraper.py — Scraper del sitio BCP (bcp.gov.py)

El sitio BCP usa Liferay Portal + Cloudflare, lo que bloquea requests simples.
Se usa Playwright (Chromium headless) para renderizar el JavaScript y extraer
los documentos de la página de Normas Vigentes.

Sección cubierta:
  - Normas Vigentes (Resoluciones + Circulares + Reglamentos del Directorio BCP
    y Superintendencia de Bancos): 697+ docs en /web/institucional/vigentes

Categorías detectadas por título:
  - circular       → "Circular SB.SG. ..."
  - reglamento     → "Reglamento ..."
  - norma_prudencial → "Norma ..."
  - resolucion     → todo lo demás (Resoluciones de Directorio, SIB, etc.)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

BCP_BASE   = "https://www.bcp.gov.py"
VIGENTES_PATH = "/web/institucional/marco-normativo1"  # entry, luego JS navega a /vigentes

# JS selector del link de normas vigentes dentro del SPA
VIGENTES_LINK_SELECTOR = 'a[href="/web/institucional/vigentes"]'
ITEM_SELECTOR           = ".list__item.search-item"
DOWNLOAD_LINK_SELECTOR  = 'a[href*="/documents/"]'


@dataclass
class DocumentRecord:
    url:       str
    category:  str
    source:    str = "bcp"
    title:     str = ""
    published: Optional[str] = None
    filename:  str = ""


def _detect_category(title: str) -> str:
    t = title.lower()
    if "circular" in t:
        return "circular"
    if "reglamento" in t:
        return "reglamento"
    if "norma" in t:
        return "norma_prudencial"
    return "resolucion"


def _parse_date(text: str) -> Optional[str]:
    """Extrae fecha de formato DD.MM.YYYY o DD.MM.YY del texto."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
    if not m:
        return None
    d, mo, y = m.groups()
    year = int("20" + y) if len(y) == 2 else int(y)
    try:
        return datetime(year, int(mo), int(d)).date().isoformat()
    except ValueError:
        return None


def run_scraper(
    categories: Optional[list[str]] = None,
) -> list[DocumentRecord]:
    """
    Abre Playwright Chromium, navega a BCP normas vigentes y extrae todos los docs.

    Args:
        categories: lista de categorías a filtrar. None = todas.
            Opciones: 'resolucion', 'circular', 'reglamento', 'norma_prudencial'

    Returns:
        Lista de DocumentRecord únicos por URL.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    records: list[DocumentRecord] = []
    seen: set[str] = set()

    log.info("=== Scraping BCP (Playwright) ===")
    log.info(f"URL entrada: {BCP_BASE}{VIGENTES_PATH}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-PY",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        # 1. Abrir la página Marco Normativo (entry point del SPA)
        log.info("  Cargando Marco Normativo...")
        page.goto(BCP_BASE + VIGENTES_PATH, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(2)

        # 2. Hacer click en el link "Vigentes" (SPA navigation)
        try:
            page.wait_for_selector(VIGENTES_LINK_SELECTOR, timeout=15_000)
            page.click(VIGENTES_LINK_SELECTOR)
            log.info("  Navegando a Vigentes...")
        except PWTimeout:
            log.warning("  Link 'Vigentes' no encontrado — intentando URL directa")
            page.goto(BCP_BASE + "/web/institucional/vigentes",
                      wait_until="domcontentloaded", timeout=60_000)

        # 3. Esperar a que carguen los items
        try:
            page.wait_for_selector(ITEM_SELECTOR, timeout=30_000)
        except PWTimeout:
            log.error("  No se encontraron items — ¿protección Cloudflare?")
            browser.close()
            return []

        # 4. Esperar a que se rendericen todos (el SPA puede tardar)
        time.sleep(3)
        item_count = page.locator(ITEM_SELECTOR).count()
        log.info(f"  Items encontrados: {item_count}")

        # 5. Extraer datos de cada item
        items = page.locator(ITEM_SELECTOR).all()
        for item in items:
            try:
                text = item.inner_text().strip()
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                title = lines[0] if lines else ""

                # Download link (excluir Vista Previa que termina en .pdf)
                # Usar evaluate() para obtener la URL absoluta resuelta
                dl_links = item.locator(DOWNLOAD_LINK_SELECTOR).all()
                url = None
                for a in dl_links:
                    # evaluate() devuelve a.href (absoluto), get_attribute devuelve relativo
                    try:
                        full_href = a.evaluate("el => el.href") or ""
                    except Exception:
                        href = a.get_attribute("href") or ""
                        full_href = href if href.startswith("http") else BCP_BASE + href

                    clean = full_href.split("?")[0]
                    # El link de descarga tiene UUID al final (no extensión .pdf)
                    # El de Vista Previa termina en .pdf
                    last_seg = clean.rstrip("/").split("/")[-1]
                    if re.match(r'^[0-9a-f\-]{36}$', last_seg):
                        # UUID al final → link de descarga real
                        url = clean
                        break
                    elif clean.lower().endswith(".pdf"):
                        # Vista Previa o link directo al PDF
                        url = clean
                        break

                if not url or url in seen:
                    continue
                seen.add(url)

                category = _detect_category(title)
                if categories and category not in categories:
                    continue

                published = _parse_date(title)

                # Filename del path
                path_parts = url.rstrip("/").split("/")
                # Encontrar el segmento .pdf
                filename = ""
                for part in reversed(path_parts):
                    decoded = part.replace("+", " ")
                    if decoded.lower().endswith(".pdf"):
                        filename = decoded
                        break
                if not filename:
                    filename = path_parts[-1].split("?")[0]

                records.append(DocumentRecord(
                    url=url,
                    title=title[:300],
                    category=category,
                    published=published,
                    filename=filename[:200],
                ))

            except Exception as e:
                log.warning(f"  Error extrayendo item: {e}")
                continue

        browser.close()

    log.info(f"Total PDFs únicos encontrados: {len(records)}")
    if categories:
        log.info(f"  (filtrado por categorías: {categories})")
    return records


if __name__ == "__main__":
    records = run_scraper()
    print(f"\n=== {len(records)} documentos ===")
    for r in records[:10]:
        print(f"  [{r.category}] {r.title[:70]}")
        print(f"    → {r.url[:80]}")
