import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from common_official import DocumentRecord, run_official_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SECTIONS = [
    {
        "category": "resolucion",
        "index_url": "https://www.mspbs.gov.py/resoluciones.html",
        "allowed_domains": ["mspbs.gov.py"],
        "max_pages": 8,
    },
    {
        "category": "reglamento",
        "index_url": "https://www.mspbs.gov.py/normativas.html",
        "allowed_domains": ["mspbs.gov.py"],
        "max_pages": 8,
    },
]


def run_scraper(categories: Optional[list[str]] = None) -> list[DocumentRecord]:
    sections = SECTIONS if not categories else [s for s in SECTIONS if s["category"] in categories]
    return run_official_scraper("mspbs", sections)


if __name__ == "__main__":
    docs = run_scraper()
    print(f"Total: {len(docs)}")
