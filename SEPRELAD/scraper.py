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
        "index_url": "https://www.seprelad.gov.py/resoluciones",
        "allowed_domains": ["seprelad.gov.py"],
        "max_pages": 15,
        "page_param": "page",
    },
    {
        "category": "reglamento",
        "index_url": "https://www.seprelad.gov.py/normativas",
        "allowed_domains": ["seprelad.gov.py"],
        "max_pages": 10,
        "page_param": "page",
    },
]


def run_scraper(categories: Optional[list[str]] = None) -> list[DocumentRecord]:
    sections = SECTIONS if not categories else [s for s in SECTIONS if s["category"] in categories]
    return run_official_scraper("seprelad", sections)


if __name__ == "__main__":
    docs = run_scraper()
    print(f"Total: {len(docs)}")
