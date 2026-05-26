"""
bdd_generator.py — Genera escenarios BDD + plan de pruebas desde chunks RAG.

Usa Claude Sonnet con un prompt estructurado que retorna JSON.
El JSON se parsea y guarda en bdd_scenarios + test_plans en Supabase.
"""

import json
import re

BDD_SYSTEM_PROMPT = """Sos un experto QA regulatorio especializado en compliance de Paraguay.
Tu tarea es analizar un requerimiento de software, las aclaraciones del usuario,
y los fragmentos de regulaciones aplicables (BCP o CONATEL) para generar:

1. Análisis regulatorio narrativo
2. Escenarios BDD en formato Gherkin (mínimo 3, máximo 6)
3. Plan de pruebas con matriz de trazabilidad

REGLAS:
- Citá siempre resoluciones/circulares concretas (número + fecha)
- Priority: "Alta" si es obligatorio por norma, "Media" si recomendado, "Baja" si buena práctica
- regulatory_risk: "Crítico" = multa/sanción directa, "Alto" = incumplimiento normativo,
  "Medio" = riesgo operacional, "Bajo" = mejora de control
- Gherkin: siempre en español, con Given/When/Then claros y verificables
- Los escenarios deben cubrir: camino feliz, casos borde, y falla/rechazo

Respondé ÚNICAMENTE con JSON válido, sin markdown, sin texto extra."""

BDD_USER_TEMPLATE = """REQUERIMIENTO DEL SISTEMA:
{requirement}

ACLARACIONES DEL USUARIO:
{answers}

INDUSTRIA DETECTADA: {industry}
TOPICS: {topics}

REGULACIONES APLICABLES (fragmentos recuperados por búsqueda semántica):
{context}

Generá el análisis en este JSON exacto:
{{
  "analysis": "<narrativa regulatoria: qué normas aplican, obligaciones, gaps — mínimo 200 palabras>",
  "bdd_scenarios": [
    {{
      "title": "<título corto del escenario>",
      "gherkin": "Feature: <nombre>\\n\\n  Background:\\n    Given <contexto>\\n\\n  Scenario: <nombre>\\n    Given <precondición>\\n    When <acción>\\n    Then <resultado>\\n    And <verificación adicional>",
      "priority": "Alta|Media|Baja",
      "regulatory_risk": "Crítico|Alto|Medio|Bajo",
      "normative_refs": ["<Resolución N°X Acta N°Y — DD.MM.AAAA>"]
    }}
  ],
  "test_plan": {{
    "title": "Plan de Pruebas — <resumen del requerimiento en 8 palabras>",
    "executive_summary": "<resumen ejecutivo: qué se prueba, por qué, riesgo regulatorio global — 3-4 oraciones>",
    "scenarios": [
      {{
        "scenario_title": "<igual que bdd_scenarios[i].title>",
        "priority": "Alta|Media|Baja",
        "regulatory_risk": "Crítico|Alto|Medio|Bajo",
        "impact": "<qué pasa si este escenario falla: consecuencia regulatoria/operacional>",
        "normative_refs": ["<Resolución N°X>"],
        "estimated_effort": "<Nh>"
      }}
    ],
    "traceability_matrix": [
      {{
        "requirement_fragment": "<parte del requerimiento que se prueba>",
        "regulation": "<norma aplicable>",
        "scenario_title": "<escenario que lo cubre>"
      }}
    ]
  }}
}}"""


def build_bdd_prompt(
    requirement: str,
    answers_text: str,
    industry: str,
    topics: list[str],
    context: str,
) -> tuple[str, str]:
    """Retorna (system_prompt, user_message)."""
    user_msg = BDD_USER_TEMPLATE.format(
        requirement=requirement,
        answers=answers_text or "Sin aclaraciones adicionales.",
        industry=industry,
        topics=", ".join(topics) if topics else "general",
        context=context,
    )
    return BDD_SYSTEM_PROMPT, user_msg


def parse_bdd_response(raw: str) -> dict:
    """
    Parsea la respuesta JSON de Claude.
    Maneja casos donde Claude incluye markdown fences o texto extra.
    """
    # Remover markdown fences si existen
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

    # Encontrar el JSON (primer { hasta último })
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No se encontró JSON en la respuesta: {raw[:200]}")

    json_str = raw[start:end]
    return json.loads(json_str)


def validate_bdd_response(data: dict) -> dict:
    """
    Valida y normaliza la respuesta. Completa campos faltantes con defaults.
    """
    valid_priority = {"Alta", "Media", "Baja"}
    valid_risk     = {"Crítico", "Alto", "Medio", "Bajo"}

    # Normalizar bdd_scenarios
    scenarios = data.get("bdd_scenarios", [])
    for s in scenarios:
        if s.get("priority") not in valid_priority:
            s["priority"] = "Media"
        if s.get("regulatory_risk") not in valid_risk:
            s["regulatory_risk"] = "Medio"
        if not isinstance(s.get("normative_refs"), list):
            s["normative_refs"] = []
        if "gherkin" not in s:
            s["gherkin"] = f"Feature: {s.get('title', 'Sin título')}\n\n  Scenario: Pendiente\n    Given el sistema está configurado\n    When se ejecuta la funcionalidad\n    Then el resultado cumple la norma"

    # Normalizar test_plan.scenarios
    plan = data.get("test_plan", {})
    for ps in plan.get("scenarios", []):
        if ps.get("priority") not in valid_priority:
            ps["priority"] = "Media"
        if ps.get("regulatory_risk") not in valid_risk:
            ps["regulatory_risk"] = "Medio"
        if "impact" not in ps:
            ps["impact"] = "Impacto no especificado."
        if "estimated_effort" not in ps:
            ps["estimated_effort"] = "4h"

    return data


def generate_bdd_with_claude(
    claude_client,
    requirement: str,
    answers_text: str,
    industry: str,
    topics: list[str],
    context: str,
    model: str = "claude-sonnet-4-5-20251022",
    max_tokens: int = 4000,
) -> dict:
    """
    Llama a Claude Sonnet y retorna el dict parseado y validado.
    """
    system_prompt, user_msg = build_bdd_prompt(
        requirement, answers_text, industry, topics, context
    )

    response = claude_client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text
    data = parse_bdd_response(raw)
    return validate_bdd_response(data)
