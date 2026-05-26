"""
clarification.py — Genera preguntas de clarificación basadas en topics detectados.

Las preguntas refinan el análisis antes de ejecutar el RAG completo.
Si no hay topics concretos → retorna lista vacía (avanza sin preguntas).
"""

from typing import TypedDict


class Question(TypedDict):
    id: str
    text: str
    multi: bool          # True = checkbox, False = radio
    options: list[str]


# Mapa topic → preguntas
_TOPIC_QUESTIONS: dict[str, list[Question]] = {
    "transferencias": [
        {
            "id": "q_transfer_protocol",
            "text": "¿Qué protocolo(s) de pago involucra el requerimiento?",
            "multi": True,
            "options": ["SPI (Sistema de Pagos Inmediatos)", "LBTR (Liquidación Bruta en Tiempo Real)", "ACH (Cámara Compensadora)", "Todos / No sé"],
        },
        {
            "id": "q_transfer_amount",
            "text": "¿En qué rango de monto opera principalmente?",
            "multi": False,
            "options": ["Menos de G. 1.000.000", "G. 1.000.000 – G. 50.000.000", "Más de G. 50.000.000", "Sin límite definido"],
        },
    ],
    "fraude_seguridad": [
        {
            "id": "q_auth_method",
            "text": "¿Qué método(s) de autenticación aplica?",
            "multi": True,
            "options": ["OTP / SMS", "Doble factor (2FA)", "Biometría", "PIN / Contraseña estática"],
        },
    ],
    "tecnologia": [
        {
            "id": "q_channel",
            "text": "¿Qué canal(es) digital(es) cubre el requerimiento?",
            "multi": True,
            "options": ["App móvil", "Web / Home banking", "ATM / Cajero", "API / B2B", "Todos"],
        },
    ],
    "riesgo": [
        {
            "id": "q_risk_type",
            "text": "¿Qué tipo de riesgo involucra?",
            "multi": True,
            "options": ["Riesgo de crédito", "Riesgo operacional", "Riesgo de liquidez", "Riesgo de mercado"],
        },
    ],
    "espectro": [
        {
            "id": "q_frequency_band",
            "text": "¿Qué banda de frecuencia aplica?",
            "multi": False,
            "options": ["700 MHz (LTE)", "AWS / 1700-2100 MHz", "2.5 GHz", "mmWave / 5G", "Otra / No definida"],
        },
    ],
    "concesiones": [
        {
            "id": "q_service_type",
            "text": "¿Qué tipo de servicio de telecomunicaciones cubre?",
            "multi": True,
            "options": ["ISP / Internet fijo", "Telefonía móvil", "Radiodifusión / TV", "Telefonía fija"],
        },
    ],
    "credito_cartera": [
        {
            "id": "q_credit_type",
            "text": "¿Qué tipo de crédito involucra?",
            "multi": True,
            "options": ["Crédito de consumo", "Crédito hipotecario", "Microcrédito", "Línea de crédito empresarial"],
        },
    ],
    "aml": [
        {
            "id": "q_aml_scope",
            "text": "¿Qué aspecto de prevención de lavado aplica?",
            "multi": True,
            "options": ["KYC / Due Diligence", "Reporte de Operación Sospechosa (ROS)", "Monitoreo de transacciones", "Listas de control / Compliance"],
        },
    ],
}

# Pregunta genérica que siempre aplica (al final)
_GENERIC_QUESTION: Question = {
    "id": "q_existing_regulation",
    "text": "¿Ya identificaste alguna regulación específica que aplique?",
    "multi": False,
    "options": ["Sí, tengo la resolución/circular", "No, quiero que el sistema la busque", "No sé"],
}


def generate_questions(topics: list[str], max_questions: int = 4) -> list[Question]:
    """
    Dado un listado de topics clasificados, retorna preguntas relevantes.

    - Máximo max_questions preguntas para no sobrecargar al usuario.
    - Si no hay topics → lista vacía (avanza directo al análisis).
    - Siempre agrega la pregunta genérica si hay al menos 1 pregunta temática.
    """
    questions: list[Question] = []
    seen_ids: set[str] = set()

    for topic in topics:
        if topic in _TOPIC_QUESTIONS:
            for q in _TOPIC_QUESTIONS[topic]:
                if q["id"] not in seen_ids:
                    questions.append(q)
                    seen_ids.add(q["id"])
                if len(questions) >= max_questions - 1:
                    break
        if len(questions) >= max_questions - 1:
            break

    if questions:
        questions.append(_GENERIC_QUESTION)

    return questions


def format_answers_for_prompt(answers: dict[str, list[str]]) -> str:
    """
    Convierte {q_id: [opciones_seleccionadas]} en texto para incluir en el prompt.
    """
    if not answers:
        return "Sin aclaraciones adicionales."

    lines = []
    label_map = {q["id"]: q["text"] for topic_qs in _TOPIC_QUESTIONS.values() for q in topic_qs}
    label_map[_GENERIC_QUESTION["id"]] = _GENERIC_QUESTION["text"]

    for q_id, selected in answers.items():
        if not selected:
            continue
        label = label_map.get(q_id, q_id)
        values = ", ".join(selected) if isinstance(selected, list) else str(selected)
        lines.append(f"- {label}: **{values}**")

    return "\n".join(lines) if lines else "Sin aclaraciones adicionales."
