import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scraper import run_scraper

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from common_official import run_indexer_for_source


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indexador RAG - SIS")
    parser.add_argument("--categories", nargs="+", choices=["resolucion", "circular"])
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-embed", action="store_true")
    args = parser.parse_args()

    run_indexer_for_source(
        "sis",
        run_scraper,
        categories=args.categories,
        reindex=args.reindex,
        limit=args.limit,
        no_embed=args.no_embed,
    )
