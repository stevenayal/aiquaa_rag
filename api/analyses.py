"""
api/analyses.py — Vercel Python Function

GET /api/analyses/<id>          → detalle completo
GET /api/analyses/<id>/bdd      → descarga .feature
GET /api/analyses/<id>/test-plan → retorna plan como JSON
"""

import json
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

from api.auth import verify_jwt, AuthError


def _cors_headers(extra: dict = None) -> dict:
    h = {
        "Access-Control-Allow-Origin": os.environ.get("FRONTEND_URL", "*"),
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


def _has_access(sb, user_id: str, analysis_id: str) -> dict | None:
    """Retorna el análisis si el user tiene acceso, None si no."""
    row = sb.table("analyses").select(
        "id, project_id, user_id, requirement_text, clarification_answers, "
        "classification, rag_chunks_used, analysis_narrative, created_at"
    ).eq("id", analysis_id).single().execute().data

    if not row:
        return None

    project_id = row["project_id"]
    is_owner  = bool(sb.table("projects").select("id").eq("id", project_id).eq("owner_id", user_id).execute().data)
    is_member = bool(sb.table("project_members").select("project_id").eq("project_id", project_id).eq("user_id", user_id).execute().data)

    if not (is_owner or is_member or row["user_id"] == user_id):
        return None

    return row


def handler(request, response):
    for k, v in _cors_headers().items():
        response.headers[k] = v

    if request.method == "OPTIONS":
        response.status_code = 204
        return

    if request.method != "GET":
        response.status_code = 405
        response.body = json.dumps({"error": "Method not allowed"})
        return

    auth_header = request.headers.get("authorization", "")
    try:
        user_id = verify_jwt(auth_header)
    except AuthError as e:
        response.status_code = e.status_code
        response.body = json.dumps({"error": str(e)})
        return

    parts = [p for p in request.path.split("/") if p]
    # ["api", "analyses", <id>]  or  ["api", "analyses", <id>, "bdd"]  etc.

    if len(parts) < 3:
        response.status_code = 400
        response.body = json.dumps({"error": "analysis_id requerido"})
        return

    analysis_id = parts[2]
    sub = parts[3] if len(parts) > 3 else None

    sb  = _sb()
    row = _has_access(sb, user_id, analysis_id)
    if not row:
        response.status_code = 404
        response.body = json.dumps({"error": "Análisis no encontrado o sin acceso"})
        return

    # GET /api/analyses/<id>
    if sub is None:
        bdd_rows   = sb.table("bdd_scenarios").select("*").eq("analysis_id", analysis_id).execute().data or []
        plan_rows  = sb.table("test_plans").select("*").eq("analysis_id", analysis_id).execute().data or []

        response.status_code = 200
        response.body = json.dumps({
            "analysis":      row,
            "bdd_scenarios": bdd_rows,
            "test_plan":     plan_rows[0] if plan_rows else None,
        }, ensure_ascii=False)
        return

    # GET /api/analyses/<id>/bdd  → descarga .feature
    if sub == "bdd":
        bdd_rows = sb.table("bdd_scenarios").select("gherkin_text, title, priority, regulatory_risk, normative_refs").eq("analysis_id", analysis_id).execute().data or []

        if not bdd_rows:
            response.status_code = 404
            response.body = json.dumps({"error": "Sin escenarios BDD generados"})
            return

        # Construir .feature unificado
        lines = [
            f"# Análisis ID: {analysis_id}",
            f"# Requerimiento: {row['requirement_text'][:120]}",
            f"# Generado: {row['created_at'][:10]}",
            "",
        ]
        for s in bdd_rows:
            lines.append(f"# Priority: {s.get('priority','—')} | Risk: {s.get('regulatory_risk','—')}")
            refs = s.get("normative_refs") or []
            if refs:
                lines.append(f"# Refs: {', '.join(refs)}")
            lines.append(s.get("gherkin_text", ""))
            lines.append("")

        feature_content = "\n".join(lines)

        response.status_code = 200
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="analysis_{analysis_id[:8]}.feature"'
        response.body = feature_content
        return

    # GET /api/analyses/<id>/test-plan  → plan JSON
    if sub == "test-plan":
        plan_rows = sb.table("test_plans").select("*").eq("analysis_id", analysis_id).execute().data
        if not plan_rows:
            response.status_code = 404
            response.body = json.dumps({"error": "Sin plan de pruebas generado"})
            return

        response.status_code = 200
        response.body = json.dumps(plan_rows[0]["content"], ensure_ascii=False)
        return

    response.status_code = 404
    response.body = json.dumps({"error": f"Sub-ruta desconocida: {sub}"})
