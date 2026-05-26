"""
api/projects.py — Vercel Python Function

Maneja CRUD de proyectos y gestión de miembros.

GET  /api/projects              → lista proyectos del usuario
POST /api/projects              → crear proyecto
POST /api/projects/[id]/members → invitar miembro por email
DELETE /api/projects/[id]/members/[uid] → remover miembro
"""

import json
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

from api.auth import verify_jwt, AuthError


def _cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": os.environ.get("FRONTEND_URL", "*"),
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json",
    }


def _sb():
    """Crea cliente Supabase con service_role (bypasa RLS para lógica server-side)."""
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


def handler(request, response):
    for k, v in _cors_headers().items():
        response.headers[k] = v

    if request.method == "OPTIONS":
        response.status_code = 204
        return

    auth_header = request.headers.get("authorization", "")
    try:
        user_id = verify_jwt(auth_header)
    except AuthError as e:
        response.status_code = e.status_code
        response.body = json.dumps({"error": str(e)})
        return

    path   = request.path   # e.g. /api/projects or /api/projects/uuid/members
    method = request.method
    parts  = [p for p in path.split("/") if p]
    # parts: ["api", "projects"] or ["api", "projects", <id>] or ["api", "projects", <id>, "members", <uid>]

    sb = _sb()

    # GET /api/projects
    if method == "GET" and len(parts) == 2:
        # Proyectos donde es owner o miembro
        owned = sb.table("projects").select(
            "id, name, description, industry, owner_id, created_at"
        ).eq("owner_id", user_id).execute().data or []

        member_of_rows = sb.table("project_members").select("project_id").eq("user_id", user_id).execute().data or []
        member_ids = [r["project_id"] for r in member_of_rows]

        if member_ids:
            member_projects = sb.table("projects").select(
                "id, name, description, industry, owner_id, created_at"
            ).in_("id", member_ids).execute().data or []
        else:
            member_projects = []

        # Dedup
        seen = {p["id"] for p in owned}
        all_projects = owned + [p for p in member_projects if p["id"] not in seen]
        all_projects.sort(key=lambda p: p["created_at"], reverse=True)

        response.status_code = 200
        response.body = json.dumps({"projects": all_projects}, ensure_ascii=False)
        return

    # POST /api/projects
    if method == "POST" and len(parts) == 2:
        try:
            body = json.loads(request.body)
        except Exception:
            response.status_code = 400
            response.body = json.dumps({"error": "Invalid JSON"})
            return

        name        = (body.get("name") or "").strip()
        industry    = (body.get("industry") or "").strip()
        description = (body.get("description") or "").strip()

        if not name:
            response.status_code = 400
            response.body = json.dumps({"error": "name is required"})
            return
        if industry not in ("banca", "telecomunicaciones"):
            response.status_code = 400
            response.body = json.dumps({"error": "industry must be 'banca' or 'telecomunicaciones'"})
            return

        row = {
            "name":        name,
            "industry":    industry,
            "description": description or None,
            "owner_id":    user_id,
        }
        res = sb.table("projects").insert(row).execute()
        project = res.data[0]

        response.status_code = 201
        response.body = json.dumps({"project": project}, ensure_ascii=False)
        return

    # POST /api/projects/<id>/members  — invitar por email
    if method == "POST" and len(parts) == 4 and parts[3] == "members":
        project_id = parts[2]

        # Verificar que el caller es owner
        proj = sb.table("projects").select("owner_id").eq("id", project_id).single().execute().data
        if not proj or proj["owner_id"] != user_id:
            response.status_code = 403
            response.body = json.dumps({"error": "Solo el owner puede invitar miembros"})
            return

        try:
            body = json.loads(request.body)
        except Exception:
            response.status_code = 400
            response.body = json.dumps({"error": "Invalid JSON"})
            return

        email = (body.get("email") or "").strip().lower()
        role  = body.get("role", "viewer")

        if not email:
            response.status_code = 400
            response.body = json.dumps({"error": "email is required"})
            return
        if role not in ("admin", "editor", "viewer"):
            role = "viewer"

        # Buscar usuario por email en auth.users via Admin API
        supabase_url = os.environ["SUPABASE_URL"]
        service_key  = os.environ["SUPABASE_SERVICE_KEY"]

        import urllib.request
        import urllib.error

        list_url = f"{supabase_url}/auth/v1/admin/users?email={email}"
        req = urllib.request.Request(
            list_url,
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey":        service_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                users_data = json.loads(resp.read())
                users = users_data.get("users", [])
        except Exception as e:
            response.status_code = 502
            response.body = json.dumps({"error": f"Error buscando usuario: {e}"})
            return

        if not users:
            response.status_code = 404
            response.body = json.dumps({"error": f"No existe usuario con email {email}"})
            return

        invited_user_id = users[0]["id"]

        # No invitar al mismo owner
        if invited_user_id == user_id:
            response.status_code = 400
            response.body = json.dumps({"error": "No puedes invitarte a ti mismo"})
            return

        # Insertar o actualizar membresía
        sb.table("project_members").upsert({
            "project_id": project_id,
            "user_id":    invited_user_id,
            "role":       role,
            "invited_by": user_id,
        }).execute()

        response.status_code = 200
        response.body = json.dumps({
            "message": f"Usuario {email} invitado como {role}",
            "user_id": invited_user_id,
        }, ensure_ascii=False)
        return

    # DELETE /api/projects/<id>/members/<uid>
    if method == "DELETE" and len(parts) == 5 and parts[3] == "members":
        project_id    = parts[2]
        target_user_id = parts[4]

        proj = sb.table("projects").select("owner_id").eq("id", project_id).single().execute().data
        if not proj or proj["owner_id"] != user_id:
            response.status_code = 403
            response.body = json.dumps({"error": "Solo el owner puede remover miembros"})
            return

        sb.table("project_members").delete().eq("project_id", project_id).eq("user_id", target_user_id).execute()
        response.status_code = 200
        response.body = json.dumps({"message": "Miembro removido"})
        return

    # GET /api/projects/<id>  — detalle de proyecto
    if method == "GET" and len(parts) == 3:
        project_id = parts[2]

        # Verificar acceso
        proj = sb.table("projects").select(
            "id, name, description, industry, owner_id, created_at"
        ).eq("id", project_id).single().execute().data

        if not proj:
            response.status_code = 404
            response.body = json.dumps({"error": "Proyecto no encontrado"})
            return

        is_owner  = proj["owner_id"] == user_id
        is_member = bool(sb.table("project_members").select("project_id").eq("project_id", project_id).eq("user_id", user_id).execute().data)

        if not is_owner and not is_member:
            response.status_code = 403
            response.body = json.dumps({"error": "Sin acceso a este proyecto"})
            return

        # Cargar miembros
        members = sb.table("project_members").select("user_id, role, invited_at").eq("project_id", project_id).execute().data or []

        # Cargar últimos análisis
        analyses = sb.table("analyses").select(
            "id, requirement_text, created_at, classification"
        ).eq("project_id", project_id).order("created_at", desc=True).limit(20).execute().data or []

        response.status_code = 200
        response.body = json.dumps({
            "project":  proj,
            "is_owner": is_owner,
            "members":  members,
            "analyses": analyses,
        }, ensure_ascii=False)
        return

    response.status_code = 404
    response.body = json.dumps({"error": "Endpoint no encontrado"})
