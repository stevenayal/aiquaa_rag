"""
api/analyze_run.py — Vercel Python Function (Paso 2)

POST /api/analyze_run
Body: {
  "requirement":  str,
  "project_id":   str,
  "answers":      { q_id: [selected_options] }   # opcional
}
Auth: Authorization: Bearer <supabase_jwt>

Ejecuta análisis completo:
  1. Clasificación (enriquecida con answers)
  2. Embed + pgvector search
  3. Claude Sonnet → análisis + BDD + plan de pruebas
  4. Guarda en analyses + bdd_scenarios + test_plans
  5. Retorna resultado completo
"""

import json
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

from api.auth import require_project_access, AuthError
from api.clarification import format_answers_for_prompt
from api.bdd_generator import generate_bdd_with_claude


def _cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": os.environ.get("FRONTEND_URL", "*"),
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json",
    }


def _save_to_supabase(
    project_id: str,
    user_id: str,
    requirement: str,
    answers: dict,
    cls,
    chunks: list[dict],
    bdd_data: dict,
) -> str:
    """
    Guarda análisis + bdd_scenarios + test_plan en Supabase.
    Retorna analysis_id.
    """
    from supabase import create_client
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )

    # Preparar chunks_used (resumen compacto)
    chunks_summary = [
        {
            "title":      c.get("doc_title", ""),
            "url":        c.get("doc_url", ""),
            "similarity": round(c.get("similarity", 0), 4),
            "category":   c.get("doc_category", ""),
        }
        for c in chunks[:20]
    ]

    # 1. Insertar análisis
    analysis_row = {
        "project_id":             project_id,
        "user_id":                user_id,
        "requirement_text":       requirement,
        "clarification_answers":  answers or {},
        "classification": {
            "industry":   cls.industry,
            "topics":     cls.topics,
            "confidence": cls.confidence,
            "search_query": cls.search_query,
        } if cls else {},
        "rag_chunks_used":   chunks_summary,
        "analysis_narrative": bdd_data.get("analysis", ""),
    }

    res = sb.table("analyses").insert(analysis_row).execute()
    analysis_id = res.data[0]["id"]

    # 2. Insertar escenarios BDD
    bdd_rows = []
    for s in bdd_data.get("bdd_scenarios", []):
        bdd_rows.append({
            "analysis_id":     analysis_id,
            "title":           s.get("title", "Sin título"),
            "gherkin_text":    s.get("gherkin", ""),
            "priority":        s.get("priority", "Media"),
            "regulatory_risk": s.get("regulatory_risk", "Medio"),
            "normative_refs":  s.get("normative_refs", []),
        })
    if bdd_rows:
        sb.table("bdd_scenarios").insert(bdd_rows).execute()

    # 3. Insertar plan de pruebas
    test_plan = bdd_data.get("test_plan", {})
    if test_plan:
        sb.table("test_plans").insert({
            "analysis_id": analysis_id,
            "title":       test_plan.get("title", f"Plan — {requirement[:60]}"),
            "content":     test_plan,
        }).execute()

    return analysis_id


def handler(request, response):
    """Entry point Vercel."""

    if request.method == "OPTIONS":
        response.status_code = 204
        for k, v in _cors_headers().items():
            response.headers[k] = v
        return

    if request.method != "POST":
        response.status_code = 405
        response.body = json.dumps({"error": "Method not allowed"})
        return

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        response.status_code = 400
        response.body = json.dumps({"error": "Invalid JSON body"})
        return

    requirement = (body.get("requirement") or "").strip()
    project_id  = (body.get("project_id") or "").strip()
    answers     = body.get("answers") or {}

    if not requirement:
        response.status_code = 400
        response.body = json.dumps({"error": "requirement is required"})
        return
    if not project_id:
        response.status_code = 400
        response.body = json.dumps({"error": "project_id is required"})
        return

    # Auth
    auth_header = request.headers.get("authorization", "")
    try:
        user_id = require_project_access(auth_header, project_id)
    except AuthError as e:
        response.status_code = e.status_code
        response.headers["Content-Type"] = "application/json"
        response.body = json.dumps({"error": str(e)})
        return

    try:
        # ── 1. Importar módulos RAG ───────────────────────────────────────
        from rag_analyzer import (
            classify_requirement, get_voyage, get_supabase, get_claude,
            embed_query, search_regulations, build_context,
        )

        # ── 2. Clasificar ─────────────────────────────────────────────────
        cls = classify_requirement(requirement)

        # ── 3. Embed + búsqueda vectorial ─────────────────────────────────
        voyage  = get_voyage()
        sb      = get_supabase()
        q_vec   = embed_query(voyage, cls.search_query)
        chunks  = search_regulations(sb, q_vec, cls, top_k=12, threshold=0.35)

        context = build_context(chunks)

        # ── 4. Formatear answers para prompt ──────────────────────────────
        answers_text = format_answers_for_prompt(answers)

        # ── 5. Claude Sonnet → BDD + test plan ───────────────────────────
        claude = get_claude()
        if not claude:
            response.status_code = 503
            response.body = json.dumps({"error": "ANTHROPIC_API_KEY no configurado"})
            return

        bdd_data = generate_bdd_with_claude(
            claude_client=claude,
            requirement=requirement,
            answers_text=answers_text,
            industry=cls.industry,
            topics=cls.topics,
            context=context,
        )

        # ── 6. Guardar en Supabase ────────────────────────────────────────
        analysis_id = _save_to_supabase(
            project_id=project_id,
            user_id=user_id,
            requirement=requirement,
            answers=answers,
            cls=cls,
            chunks=chunks,
            bdd_data=bdd_data,
        )

        # ── 7. Respuesta ──────────────────────────────────────────────────
        result = {
            "analysis_id":  analysis_id,
            "classification": {
                "industry":   cls.industry,
                "topics":     cls.topics,
                "confidence": cls.confidence,
            },
            "chunks_used":      len(chunks),
            "analysis":         bdd_data.get("analysis", ""),
            "bdd_scenarios":    bdd_data.get("bdd_scenarios", []),
            "test_plan":        bdd_data.get("test_plan", {}),
        }

        response.status_code = 200
        for k, v in _cors_headers().items():
            response.headers[k] = v
        response.body = json.dumps(result, ensure_ascii=False)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        response.status_code = 500
        response.headers["Content-Type"] = "application/json"
        for k, v in _cors_headers().items():
            response.headers[k] = v
        response.body = json.dumps({
            "error": str(e),
            "detail": tb if os.environ.get("DEBUG") == "1" else None,
        }, ensure_ascii=False)
