"""
QA/data_indexer.py — Indexa contenido QA estructurado (JSON) al RAG.

Convierte heurísticas de testing y patrones de prueba por industria
en chunks con metadata rica, listos para embedding.

Uso:
  python QA/data_indexer.py                        # todo
  python QA/data_indexer.py --source heuristics    # solo heurísticas
  python QA/data_indexer.py --source fintech        # solo patrones fintech
  python QA/data_indexer.py --source salud          # solo patrones salud
  python QA/data_indexer.py --source retail         # solo patrones retail
  python QA/data_indexer.py --no-embed              # chunks sin embedding
  python QA/data_indexer.py --reindex               # borra y reindexea
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from common_official import (
    embed_chunks,
    delete_existing_chunks,
    mark_document_indexed,
    get_supabase,
    get_voyage,
)
from dotenv import load_dotenv

_root = Path(__file__).parent.parent
_main = _root.parent.parent.parent

for _env in [
    _root / ".env",
    _root / "BCP" / ".env",
    _root / "CONATEL" / ".env",
    _main / "BCP" / ".env",
    _main / "CONATEL" / ".env",
]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

# ── Fuentes de datos disponibles ──────────────────────────────────────────────

SOURCES = {
    "heuristics": {
        "file": DATA_DIR / "heuristics.json",
        "doc_source": "qa_heuristics",
        "doc_category": "heuristic",
        "doc_title": "Heurísticas de Testing QA: SFDIPOT, FEW HICCUPPS, CRISP, OWASP Top 10",
        "doc_url": "internal://qa/heuristics",
    },
    "fintech": {
        "file": DATA_DIR / "industry_patterns" / "fintech.json",
        "doc_source": "qa_patterns_fintech",
        "doc_category": "industry_pattern",
        "doc_title": "Patrones de Prueba Fintech: Pagos, KYC, Fraude, Reconciliación",
        "doc_url": "internal://qa/patterns/fintech",
    },
    "salud": {
        "file": DATA_DIR / "industry_patterns" / "salud.json",
        "doc_source": "qa_patterns_salud",
        "doc_category": "industry_pattern",
        "doc_title": "Patrones de Prueba Salud: Medicación, Identidad de Paciente, Alertas Clínicas",
        "doc_url": "internal://qa/patterns/salud",
    },
    "retail": {
        "file": DATA_DIR / "industry_patterns" / "retail.json",
        "doc_source": "qa_patterns_retail",
        "doc_category": "industry_pattern",
        "doc_title": "Patrones de Prueba Retail: Carrito, Stock, Descuentos, Devoluciones",
        "doc_url": "internal://qa/patterns/retail",
    },
}


def _build_heuristic_chunks(data: list[dict]) -> list[dict]:
    """Convierte heurísticas JSON en chunks de texto."""
    chunks = []

    for heuristic in data:
        name = heuristic["name"]
        full_name = heuristic.get("full_name", name)
        description = heuristic.get("description", "")
        use_case = heuristic.get("use_case", "")
        topics = heuristic.get("topics", [])
        related = heuristic.get("related_techniques", [])

        # Chunk 1: descripción general de la heurística
        overview = (
            f"# Heurística: {name} ({full_name})\n\n"
            f"{description}\n\n"
            f"**Cuándo usar:** {use_case}\n\n"
            f"**Técnicas relacionadas:** {', '.join(related)}"
        )
        chunks.append({
            "content": overview,
            "topics": topics,
            "sub_type": "heuristic_overview",
            "name": name,
        })

        # Chunk 2: cada item como contexto de aplicación
        items = heuristic.get("items", {})
        items_text = f"# {name} — Cómo aplicar cada dimensión\n\n"
        for key, val in items.items():
            items_text += f"**{key}:** {val}\n\n"
        chunks.append({
            "content": items_text,
            "topics": topics,
            "sub_type": "heuristic_items",
            "name": name,
        })

        # Chunk 3: ejemplo de aplicación si existe
        example = heuristic.get("example_application")
        if example:
            example_text = f"# {name} — Ejemplo de aplicación\n\n{example}"
            chunks.append({
                "content": example_text,
                "topics": topics,
                "sub_type": "heuristic_example",
                "name": name,
            })

    return chunks


def _build_industry_chunks(data: dict) -> list[dict]:
    """Convierte patrones de industria JSON en chunks de texto."""
    chunks = []
    industry = data.get("industry", "")
    description = data.get("description", "")

    # Chunk resumen de la industria
    summary = f"# Patrones de Prueba: {industry.upper()}\n\n{description}"
    chunks.append({
        "content": summary,
        "topics": ["risk_based_testing", "gestion_pruebas"],
        "sub_type": "industry_overview",
        "industry": industry,
    })

    for area in data.get("risk_areas", []):
        area_name = area["area"]
        risk = area["risk"]
        area_desc = area["description"]
        technique = area.get("istqb_technique", "")
        topics = _infer_industry_topics(industry, area_name, technique)

        # Chunk 1: descripción del área de riesgo + técnica
        area_text = (
            f"# {area_name} — {industry.upper()} (Riesgo: {risk})\n\n"
            f"{area_desc}\n\n"
            f"**Técnica ISTQB recomendada:** {technique}"
        )
        chunks.append({
            "content": area_text,
            "topics": topics,
            "sub_type": "risk_area",
            "industry": industry,
            "risk_area": area_name,
            "risk_level": risk,
        })

        # Chunk 2: casos de prueba del área
        test_cases = area.get("test_cases", [])
        if test_cases:
            cases_text = f"# Casos de Prueba: {area_name} ({industry.upper()})\n\n"
            for tc in test_cases:
                cases_text += (
                    f"**{tc['id']}: {tc['title']}** [Prioridad: {tc['priority']}]\n"
                    f"Condición: {tc['condition']}\n"
                    f"Resultado esperado: {tc['expected']}\n\n"
                )
            chunks.append({
                "content": cases_text,
                "topics": topics,
                "sub_type": "test_cases",
                "industry": industry,
                "risk_area": area_name,
                "risk_level": risk,
            })

        # Chunk 3: casos negativos
        negative = area.get("negative_cases", [])
        if negative:
            neg_text = (
                f"# Casos Negativos y Edge Cases: {area_name} ({industry.upper()})\n\n"
                + "\n".join(f"- {n}" for n in negative)
            )
            chunks.append({
                "content": neg_text,
                "topics": topics,
                "sub_type": "negative_cases",
                "industry": industry,
                "risk_area": area_name,
            })

    return chunks


def _infer_industry_topics(industry: str, area_name: str, technique: str) -> list[str]:
    """Infiere topics QA desde la industria y el área de riesgo."""
    base = ["risk_based_testing"]
    area_lower = area_name.lower() + " " + technique.lower()

    if "seguridad" in area_lower or "owasp" in area_lower or "fraude" in area_lower:
        base.extend(["seguridad", "seguridad_web"])
    if "concurrencia" in area_lower or "concurrente" in area_lower:
        base.append("tecnicas_experiencia")
    if "tabla de decision" in area_lower:
        base.append("tecnicas_caja_negra")
    if "valor limite" in area_lower or "particion" in area_lower:
        base.append("tecnicas_caja_negra")
    if "transicion de estado" in area_lower:
        base.append("tecnicas_caja_negra")
    if "privacidad" in area_lower or "compliance" in area_lower or "hipaa" in area_lower:
        base.extend(["compliance", "seguridad"])
    if "rendimiento" in area_lower or "performance" in area_lower or "carga" in area_lower:
        base.append("performance")

    return list(dict.fromkeys(base))  # deduplica preservando orden


def upsert_internal_document(sb, source_key: str, source_cfg: dict,
                              reindex: bool = False) -> Optional[str]:
    """Crea o actualiza el registro en rag_documents para contenido interno."""
    data = {
        "source":   source_cfg["doc_source"],
        "url":      source_cfg["doc_url"],
        "title":    source_cfg["doc_title"],
        "category": source_cfg["doc_category"],
        "industry": "qa",
        "topics":   [],
        "filename": source_key + ".json",
    }
    try:
        res = sb.table("rag_documents").upsert(data, on_conflict="url").execute()
        doc_id = res.data[0]["id"]
        if reindex:
            delete_existing_chunks(sb, doc_id)
        return doc_id
    except Exception as e:
        log.error(f"Error upsert document {source_key}: {e}")
        return None


def insert_qa_chunks(sb, document_id: str, chunks: list[dict],
                     source_cfg: dict,
                     embeddings: Optional[list[list[float]]] = None) -> bool:
    """Inserta chunks con metadata QA enriquecida."""
    rows = []
    for i, chunk in enumerate(chunks):
        meta = {
            "industry":    "qa",
            "source":      source_cfg["doc_source"],
            "category":    source_cfg["doc_category"],
            "doc_title":   source_cfg["doc_title"],
            "lang":        "es",
            "topics":      chunk.get("topics", []),
            "source_type": chunk.get("sub_type", "pattern"),
        }
        if "industry" in chunk:
            meta["domain"] = chunk["industry"]
        if "risk_level" in chunk:
            meta["risk_level"] = chunk["risk_level"]
        if "name" in chunk:
            meta["heuristic_name"] = chunk["name"]

        row = {
            "document_id": document_id,
            "chunk_index": i,
            "content":     chunk["content"],
            "token_count": len(chunk["content"]) // 4,
            "metadata":    meta,
        }
        if embeddings is not None:
            row["embedding"] = embeddings[i]
        rows.append(row)

    try:
        sb.table("rag_chunks").insert(rows).execute()
        return True
    except Exception as e:
        log.error(f"Error insertando chunks: {e}")
        return False


def index_source(sb, source_key: str, source_cfg: dict,
                 reindex: bool = False,
                 no_embed: bool = False,
                 voyage=None) -> bool:
    file_path = source_cfg["file"]
    if not file_path.exists():
        log.error(f"Archivo no encontrado: {file_path}")
        return False

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    # Construir chunks según el tipo de fuente
    if source_key == "heuristics":
        chunks = _build_heuristic_chunks(data)
    else:
        chunks = _build_industry_chunks(data)

    log.info(f"  {len(chunks)} chunks construidos desde {file_path.name}")

    doc_id = upsert_internal_document(sb, source_key, source_cfg, reindex=reindex)
    if not doc_id:
        return False

    if no_embed:
        ok = insert_qa_chunks(sb, doc_id, chunks, source_cfg, embeddings=None)
    else:
        if voyage is None:
            voyage = get_voyage()
        texts = [c["content"] for c in chunks]
        embs = embed_chunks(voyage, texts)
        ok = insert_qa_chunks(sb, doc_id, chunks, source_cfg, embeddings=embs)

    mark_document_indexed(sb, doc_id, error=None if ok else "Error insertando chunks")
    return ok


def run(sources_filter: Optional[list[str]] = None,
        reindex: bool = False,
        no_embed: bool = False):

    sb = get_supabase()
    voyage = None if no_embed else get_voyage()

    mode = "sin embeddings" if no_embed else "con embeddings"
    log.info(f"=== Indexando datos QA estructurados [{mode}] ===")

    targets = {k: v for k, v in SOURCES.items()
               if not sources_filter or k in sources_filter}

    ok_count = fail_count = 0
    for source_key, source_cfg in targets.items():
        log.info(f"[{source_key}] {source_cfg['doc_title'][:60]}")
        success = index_source(sb, source_key, source_cfg,
                               reindex=reindex, no_embed=no_embed, voyage=voyage)
        if success:
            ok_count += 1
        else:
            fail_count += 1
        time.sleep(0.3)

    log.info("=== Indexación datos QA completa ===")
    log.info(f"  Exitosos : {ok_count}")
    log.info(f"  Fallidos : {fail_count}")
    if no_embed:
        log.info("  Embeddings pendientes. Correr:")
        for key in targets:
            log.info(f"    python re_embedder.py --source {SOURCES[key]['doc_source']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Indexa heurísticas y patrones de industria QA al RAG"
    )
    parser.add_argument("--source", choices=list(SOURCES.keys()), action="append",
                        dest="sources", metavar="SOURCE",
                        help="Indexar solo esta fuente (repetible)")
    parser.add_argument("--no-embed",  action="store_true",
                        help="Omite embeddings (Voyage AI)")
    parser.add_argument("--reindex",   action="store_true",
                        help="Borra chunks existentes y reindexea")
    args = parser.parse_args()

    run(sources_filter=args.sources, reindex=args.reindex, no_embed=args.no_embed)
