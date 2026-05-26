"""
api/analyze_questions.py — Vercel Python Function (Paso 1)

POST /api/analyze_questions
Body:  { "requirement": str, "project_id": str }
Auth:  Authorization: Bearer <supabase_jwt>

Clasifica el requerimiento y devuelve preguntas de clarificación.
El frontend muestra las preguntas antes de ejecutar el análisis completo.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Agregar root al path para importar módulos del proyecto
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

from api.auth import require_project_access, AuthError
from api.clarification import generate_questions, format_answers_for_prompt


def _cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": os.environ.get("FRONTEND_URL", "*"),
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json",
    }


def _json_response(data: dict, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": _cors_headers(),
        "body": json.dumps(data, ensure_ascii=False),
    }


def handler(request, response):
    """Entry point para Vercel Python runtime."""

    # Handle CORS preflight
    if request.method == "OPTIONS":
        response.status_code = 204
        for k, v in _cors_headers().items():
            response.headers[k] = v
        return

    if request.method != "POST":
        response.status_code = 405
        response.headers["Content-Type"] = "application/json"
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

    if not requirement:
        response.status_code = 400
        response.body = json.dumps({"error": "requirement is required"})
        return

    # Validar JWT + acceso al proyecto
    auth_header = request.headers.get("authorization", "")
    try:
        user_id = require_project_access(auth_header, project_id)
    except AuthError as e:
        response.status_code = e.status_code
        response.headers["Content-Type"] = "application/json"
        response.body = json.dumps({"error": str(e)})
        return

    # Clasificar requerimiento (keyword rules primero, Claude Haiku si hay API key)
    try:
        # Import lazy para evitar carga en tiempo de parsing de Vercel
        from rag_analyzer import classify_requirement
        cls = classify_requirement(requirement)
    except Exception as e:
        # Fallback: sin clasificación si hay error de import
        cls = None

    # Generar preguntas
    topics = cls.topics if cls else []
    questions = generate_questions(topics, max_questions=4)

    result = {
        "classification": {
            "industry":   cls.industry  if cls else "ninguna",
            "topics":     cls.topics    if cls else [],
            "confidence": cls.confidence if cls else "baja",
        } if cls else None,
        "questions": questions,
        "has_questions": len(questions) > 0,
    }

    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    for k, v in _cors_headers().items():
        response.headers[k] = v
    response.body = json.dumps(result, ensure_ascii=False)
