"""
QA/indexer.py — Indexa syllabi oficiales ISTQB al RAG.

PDFs fuente:
  - CTFL v4.0 (ES): https://aiquaa.com/resources/istqb/CTFL-v4.0-ES-Programa-de-Estudio.pdf
  - Performance JMeter (ES): https://aiquaa.com/resources/performance/PtU_Certified_Performance_Tester_with_JMeter_Syllabus_SPN_Ver.1.1.pdf
  - Performance JMeter (EN): https://aiquaa.com/resources/performance/PtU_Certified_Performance_Tester_with_JMeter_Syllabus_ENG_Ver.1.1.pdf

Uso:
  python QA/indexer.py                        # todo, con embeddings
  python QA/indexer.py --no-embed             # solo chunks, embed luego
  python QA/indexer.py --reindex              # borra chunks y reindexea
  python QA/indexer.py --source ctfl          # solo CTFL v4.0
  python QA/indexer.py --source performance   # solo syllabi JMeter
"""

import argparse
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
    DocumentRecord,
    download_pdf,
    extract_text_from_pdf,
    split_into_chunks,
    embed_chunks,
    delete_existing_chunks,
    mark_document_indexed,
    get_supabase,
    get_voyage,
)
from dotenv import load_dotenv

_root = Path(__file__).parent.parent
_main_repo = _root.parent.parent.parent  # worktrees/name/ → worktrees/ → .claude/ → main repo

for _env in [
    _root / ".env",
    _root / "BCP" / ".env",
    _root / "CONATEL" / ".env",
    _main_repo / "BCP" / ".env",
    _main_repo / "CONATEL" / ".env",
    Path(__file__).parent / ".env",
]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Parámetros de chunking QA (más granular que el default 800/150) ───────────

CHUNK_SIZE    = 900
CHUNK_OVERLAP = 120

# ── Documentos a indexar ───────────────────────────────────────────────────────

DOCUMENTS: list[DocumentRecord] = [
    DocumentRecord(
        url="https://aiquaa.com/resources/istqb/CTFL-v4.0-ES-Programa-de-Estudio.pdf",
        category="syllabus_ctfl",
        source="istqb_ctfl",
        title="ISTQB CTFL v4.0 — Programa de Estudio (ES)",
        filename="CTFL-v4.0-ES-Programa-de-Estudio.pdf",
    ),
    DocumentRecord(
        url="https://aiquaa.com/resources/performance/PtU_Certified_Performance_Tester_with_JMeter_Syllabus_SPN_Ver.1.1.pdf",
        category="syllabus_performance",
        source="istqb_performance",
        title="ISTQB Performance Tester JMeter — Syllabus (ES)",
        filename="PtU_Certified_Performance_Tester_JMeter_SPN.pdf",
    ),
    DocumentRecord(
        url="https://aiquaa.com/resources/performance/PtU_Certified_Performance_Tester_with_JMeter_Syllabus_ENG_Ver.1.1.pdf",
        category="syllabus_performance",
        source="istqb_performance",
        title="ISTQB Performance Tester JMeter — Syllabus (EN)",
        filename="PtU_Certified_Performance_Tester_JMeter_ENG.pdf",
    ),
]

# ── Mapeo de keywords → topics QA ─────────────────────────────────────────────
# Usado para enriquecer metadata de cada chunk con los topics que cubre.

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "fundamentos_testing":  [
        "fundamentos", "principios del testing", "por que es necesario",
        "testing y calidad", "errores", "defectos", "fallos",
        "nivel de prueba", "tipo de prueba", "prueba de aceptacion",
        "prueba de sistema", "prueba de integracion", "prueba unitaria",
        "testing exploratorio", "seven testing principles",
    ],
    "proceso_prueba": [
        "proceso de prueba", "ciclo de vida", "planificacion de prueba",
        "analisis de prueba", "diseño de prueba", "ejecucion de prueba",
        "cierre de prueba", "actividades de prueba", "contexto del testing",
        "test process", "test lifecycle",
    ],
    "tecnicas_caja_negra": [
        "caja negra", "black-box", "black box",
        "particion de equivalencia", "equivalence partitioning",
        "valor limite", "boundary value", "tabla de decision",
        "decision table", "transicion de estado", "state transition",
        "caso de uso", "use case testing",
    ],
    "tecnicas_caja_blanca": [
        "caja blanca", "white-box", "white box",
        "cobertura de sentencia", "statement coverage",
        "cobertura de rama", "branch coverage",
        "cobertura de condicion", "condition coverage",
        "cobertura de decision", "decision coverage",
        "mc/dc", "ruta basica",
    ],
    "tecnicas_experiencia": [
        "basado en experiencia", "experience-based",
        "prueba exploratorio", "exploratory testing",
        "basado en error", "error guessing",
        "prueba basada en lista", "checklist-based",
        "testing estatico", "static testing",
        "revision", "inspeccion", "walkthrough", "revision tecnica",
    ],
    "gestion_pruebas": [
        "gestion de pruebas", "test management",
        "planificacion", "estimacion", "monitorizacion",
        "control de pruebas", "plan de prueba", "test plan",
        "trazabilidad", "traceability",
        "lider de pruebas", "test manager", "test lead",
        "independencia del testing",
    ],
    "defect_management": [
        "gestion de defectos", "defect management",
        "informe de defecto", "defect report", "bug report",
        "ciclo de vida del defecto", "defect lifecycle",
        "causa raiz", "root cause",
        "clasificacion de defecto", "severidad", "prioridad defecto",
    ],
    "risk_based_testing": [
        "riesgo", "risk-based testing", "prueba basada en riesgo",
        "nivel de riesgo", "risk level", "riesgo de producto",
        "riesgo de proyecto", "mitigacion de riesgo",
        "analisis de riesgo", "risk identification",
    ],
    "automatizacion": [
        "automatizacion", "herramienta de prueba", "test tool",
        "prueba automatizada", "automated testing",
        "script", "marco de prueba", "test framework",
        "ci/cd", "integracion continua", "entrega continua",
        "selenium", "pytest", "robot framework", "cucumber",
    ],
    "performance": [
        "performance", "rendimiento", "prueba de carga", "load testing",
        "prueba de estres", "stress testing", "prueba de volumen",
        "throughput", "latencia", "tiempo de respuesta",
        "concurrencia", "usuarios concurrentes",
        "jmeter", "apache jmeter",
        "tpu", "performance tester", "performance testing",
        "prueba de pico", "spike testing", "soak testing",
        "monitoreo de rendimiento", "metricas de rendimiento",
        "percentil", "think time", "ramp up",
    ],
    "metricas_calidad": [
        "metrica", "indicador", "kpi",
        "densidad de defecto", "defect density",
        "cobertura de prueba", "test coverage",
        "tasa de deteccion", "detection rate",
        "eficiencia de remocion", "defect removal efficiency",
        "velocidad de prueba", "productividad",
    ],
}


def _detect_lang(filename: str) -> str:
    """Detecta idioma desde el nombre del archivo."""
    return "en" if "ENG" in filename.upper() else "es"


def _detect_topics(content: str) -> list[str]:
    """Detecta topics QA en el contenido de un chunk."""
    text_lower = content.lower()
    matched = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in text_lower for kw in keywords):
            matched.append(topic)
    return matched


def upsert_document_qa(sb, record: DocumentRecord) -> Optional[str]:
    """Upsert en rag_documents con industry='qa' fijado."""
    data = {
        "source":    record.source,
        "url":       record.url,
        "title":     record.title,
        "category":  record.category,
        "published": record.published,
        "filename":  record.filename,
        "industry":  "qa",
        "topics":    [],
    }
    try:
        res = sb.table("rag_documents").upsert(data, on_conflict="url").execute()
        return res.data[0]["id"]
    except Exception as e:
        log.error(f"Error upsert {record.url}: {e}")
        return None


def insert_chunks_qa(sb, document_id: str, chunks: list[dict],
                     record: DocumentRecord,
                     embeddings: Optional[list[list[float]]] = None) -> bool:
    """Inserta chunks con metadata rica QA."""
    lang = _detect_lang(record.filename)
    rows = []
    for i, chunk in enumerate(chunks):
        topics = _detect_topics(chunk["content"])
        row = {
            "document_id": document_id,
            "chunk_index": chunk["chunk_index"],
            "content":     chunk["content"],
            "token_count": chunk["token_count"],
            "metadata": {
                "industry":       "qa",
                "source":         record.source,
                "category":       record.category,
                "doc_title":      record.title,
                "lang":           lang,
                "topics":         topics,
                "source_type":    "syllabus",
            },
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


def index_document_qa(sb, record: DocumentRecord,
                      reindex: bool = False,
                      no_embed: bool = False,
                      voyage=None) -> bool:
    doc_id = upsert_document_qa(sb, record)
    if not doc_id:
        return False

    if reindex:
        delete_existing_chunks(sb, doc_id)

    pdf_bytes = download_pdf(record.url)
    if not pdf_bytes:
        mark_document_indexed(sb, doc_id, error="No se pudo descargar PDF")
        return False

    text = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        mark_document_indexed(sb, doc_id, error="No se extrajo texto del PDF")
        return False

    chunks = split_into_chunks(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        mark_document_indexed(sb, doc_id, error="Sin chunks generados")
        return False

    log.info(f"  {len(chunks)} chunks generados")

    if no_embed:
        ok = insert_chunks_qa(sb, doc_id, chunks, record, embeddings=None)
    else:
        if voyage is None:
            voyage = get_voyage()
        embs = embed_chunks(voyage, [c["content"] for c in chunks])
        ok = insert_chunks_qa(sb, doc_id, chunks, record, embeddings=embs)

    mark_document_indexed(sb, doc_id, error=None if ok else "Error insertando chunks")
    return ok


def run(source_filter: Optional[str] = None,
        reindex: bool = False,
        no_embed: bool = False):

    sb = get_supabase()
    voyage = None if no_embed else get_voyage()

    mode = "sin embeddings" if no_embed else "con embeddings"
    log.info(f"=== Indexando ISTQB QA [{mode}] ===")

    docs = DOCUMENTS
    if source_filter == "ctfl":
        docs = [d for d in DOCUMENTS if d.source == "istqb_ctfl"]
    elif source_filter == "performance":
        docs = [d for d in DOCUMENTS if d.source == "istqb_performance"]

    ok_count = fail_count = 0
    for i, record in enumerate(docs, 1):
        log.info(f"[{i}/{len(docs)}] {record.title}")
        success = index_document_qa(sb, record, reindex=reindex,
                                    no_embed=no_embed, voyage=voyage)
        if success:
            ok_count += 1
        else:
            fail_count += 1
        time.sleep(0.3)

    log.info("=== Indexación QA/ISTQB completa ===")
    log.info(f"  Exitosos : {ok_count}")
    log.info(f"  Fallidos : {fail_count}")
    if no_embed:
        log.info("  Embeddings pendientes. Correr:")
        log.info("    python re_embedder.py --source istqb_ctfl")
        log.info("    python re_embedder.py --source istqb_performance")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indexa syllabi ISTQB al RAG")
    parser.add_argument("--no-embed",  action="store_true",
                        help="Omite embeddings (Voyage AI). Corre re_embedder.py después.")
    parser.add_argument("--reindex",   action="store_true",
                        help="Borra chunks existentes y reindexea.")
    parser.add_argument("--source",    choices=["ctfl", "performance"],
                        help="Indexa solo un subset (ctfl|performance).")
    args = parser.parse_args()

    run(source_filter=args.source, reindex=args.reindex, no_embed=args.no_embed)
