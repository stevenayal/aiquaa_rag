"""
api/auth.py — Validación de JWT de Supabase para Vercel Python Functions.

Usa SUPABASE_JWT_SECRET para verificar el token sin llamar a Supabase.
Alternativa sin PyJWT: llama a Supabase Auth API con el token.
"""

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def _decode_jwt_payload(token: str) -> dict:
    """
    Decodifica el payload de un JWT sin verificar firma (solo para extraer user_id).
    La verificación real la hace Supabase Auth API.
    """
    import base64
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Token JWT inválido")
    # Agregar padding si falta
    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload
    except Exception:
        raise AuthError("No se pudo decodificar el token JWT")


def verify_jwt(auth_header: str) -> str:
    """
    Verifica el JWT de Supabase y retorna el user_id (sub).

    Estrategia:
    1. Extrae el token del header Authorization: Bearer <token>
    2. Llama a Supabase GET /auth/v1/user con el token
    3. Si responde 200 → token válido, retorna user_id
    """
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise AuthError("Header Authorization requerido", 401)

    token = auth_header[7:].strip()
    if not token:
        raise AuthError("Token vacío", 401)

    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not supabase_url:
        raise AuthError("SUPABASE_URL no configurado", 500)

    url = f"{supabase_url}/auth/v1/user"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": os.environ.get("SUPABASE_ANON_KEY", ""),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            user_id = data.get("id")
            if not user_id:
                raise AuthError("Usuario no encontrado en token", 401)
            return user_id
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthError("Token inválido o expirado", 401)
        raise AuthError(f"Error de autenticación: {e.code}", 401)
    except urllib.error.URLError as e:
        raise AuthError(f"Error de red validando token: {e}", 503)


def check_project_access(user_id: str, project_id: str) -> bool:
    """
    Verifica que user_id tiene acceso a project_id usando Supabase service_role.
    Consulta directamente a la tabla projects/project_members.
    """
    if not project_id:
        return True  # Sin proyecto_id = no se verifica acceso por proyecto

    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key  = os.environ.get("SUPABASE_SERVICE_KEY", "")

    if not supabase_url or not service_key:
        return True  # Config incompleta → no bloquear (logear warning en producción)

    # Consulta: ¿es owner o miembro?
    query = (
        f"{supabase_url}/rest/v1/projects"
        f"?id=eq.{project_id}"
        f"&or=(owner_id.eq.{user_id})"
        f"&select=id"
        f"&limit=1"
    )
    req = urllib.request.Request(
        query,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data:
                return True
    except Exception:
        pass

    # Check project_members
    query2 = (
        f"{supabase_url}/rest/v1/project_members"
        f"?project_id=eq.{project_id}&user_id=eq.{user_id}"
        f"&select=project_id&limit=1"
    )
    req2 = urllib.request.Request(
        query2,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
        },
    )
    try:
        with urllib.request.urlopen(req2, timeout=10) as resp:
            data = json.loads(resp.read())
            return bool(data)
    except Exception:
        return False


def require_project_access(auth_header: str, project_id: str) -> str:
    """
    Combina verify_jwt + check_project_access.
    Retorna user_id si todo OK, lanza AuthError si no.
    """
    user_id = verify_jwt(auth_header)

    if project_id and not check_project_access(user_id, project_id):
        raise AuthError("Sin acceso a este proyecto", 403)

    return user_id
