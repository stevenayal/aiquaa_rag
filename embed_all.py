"""
embed_all.py — Embeda todos los chunks pendientes de más reciente a más viejo.

Estrategia:
  1. Resoluciones por año (2026 → 2001) — las más críticas para análisis regulatorio
  2. Circulares por año (2026 → más viejo)
  3. Resto sin filtro de año (normas, decretos, leyes, CONATEL sin fecha)

Uso:
  python embed_all.py                   # todo
  python embed_all.py --category resolucion  # solo resoluciones
  python embed_all.py --from-year 2018  # desde 2018 en adelante
  python embed_all.py --dry-run         # solo muestra el plan, no embeda
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PYTHON = sys.executable

# Años con docs BCP (orden: más reciente → más viejo)
BCP_YEARS = list(range(2026, 2000, -1))

# Categorías con filtro de año
DATED_CATEGORIES = ["resolucion", "circular", "reglamento", "norma_prudencial"]

# Categorías sin filtro de año (leyes, decretos, CONATEL sin fecha)
UNDATED_PASS = [
    # CONATEL (published IS NULL en su mayoría)
    {"source": "conatel"},
    # BCP: docs sin fecha publicada
    {"source": "bcp"},
]


def run_embedder(args_extra: list[str], dry_run: bool) -> bool:
    """Lanza re_embedder.py con los args dados. Retorna True si OK."""
    cmd = [PYTHON, "re_embedder.py", "--batch-size", "128"] + args_extra
    if dry_run:
        cmd.append("--dry-run")

    log.info(f">>> {' '.join(cmd[2:])}")   # sin el python path
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    return result.returncode == 0


def count_pending(source=None, category=None, year=None) -> int:
    """Cuenta chunks pendientes para un filtro dado."""
    args = ["--dry-run"]
    if source:   args += ["--source", source]
    if category: args += ["--category", category]
    if year:     args += ["--year", str(year)]

    cmd = [PYTHON, "re_embedder.py"] + args
    result = subprocess.run(cmd, capture_output=True, text=True,
                             cwd=Path(__file__).parent)
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        if "Chunks sin embedding:" in line:
            try:
                return int(line.split(":")[-1].strip().replace(",", ""))
            except ValueError:
                pass
    return -1


def main():
    parser = argparse.ArgumentParser(description="Embeda todos los chunks pendientes por prioridad")
    parser.add_argument("--category", choices=DATED_CATEGORIES,
                        help="Solo esta categoría (default: todas)")
    parser.add_argument("--from-year", type=int, default=None,
                        help="Solo años >= este valor (default: todos)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostrar plan sin ejecutar")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("EMBED ALL — plan de embedding por prioridad")
    log.info("=" * 60)

    categories = [args.category] if args.category else DATED_CATEGORIES

    # ── Fase 1: por año (más reciente primero) ──────────────────────────────
    log.info("\n── FASE 1: docs con fecha (año por año) ──")
    total_skipped = 0
    total_runs    = 0

    for year in BCP_YEARS:
        if args.from_year and year < args.from_year:
            continue
        for cat in categories:
            pending = count_pending(category=cat, year=year)
            if pending <= 0:
                total_skipped += 1
                continue
            log.info(f"  {year} / {cat}: {pending:,} chunks pendientes")
            total_runs += 1
            if not args.dry_run:
                ok = run_embedder(["--category", cat, "--year", str(year)], dry_run=False)
                if not ok:
                    log.error(f"  FALLÓ {year}/{cat} — abortando")
                    return

    # ── Fase 2: sin filtro de año (CONATEL, BCP sin fecha) ──────────────────
    if not args.category:   # solo si no se filtró por categoría específica
        log.info("\n── FASE 2: docs sin fecha (CONATEL + BCP histórico) ──")
        for pass_args in UNDATED_PASS:
            source = pass_args.get("source")
            pending = count_pending(source=source)
            if pending <= 0:
                continue
            log.info(f"  source={source}: {pending:,} chunks pendientes")
            total_runs += 1
            if not args.dry_run:
                extra = ["--source", source] if source else []
                ok = run_embedder(extra, dry_run=False)
                if not ok:
                    log.error(f"  FALLÓ source={source} — abortando")
                    return

    log.info(f"\n{'='*60}")
    if args.dry_run:
        log.info(f"DRY RUN — {total_runs} runs pendientes, {total_skipped} ya completos")
    else:
        log.info("EMBED ALL COMPLETADO")


if __name__ == "__main__":
    main()
