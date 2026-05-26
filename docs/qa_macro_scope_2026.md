# QA Macro + Alcance de Industrias (sin BCP/CONATEL)

Fecha: 2026-05-25

## Decisión de foco

- Excluir del alcance inmediato: `bcp` (banca BCP) y `conatel` (telecom CONATEL).
- Priorizar: `qa` como macro-dominio transversal para entrenamiento y recuperación semántica.
- Mantener evaluación de alcance para industrias restantes (2025+):
  - `fintech`, `seguros`, `salud`, `energia`, `retail`, `logistica`, `gobierno`, `educacion`, `agroindustria`, `manufactura`, `banca` (sin BCP), `telecomunicaciones` (sin CONATEL).

## Matriz de viabilidad (scraping + valor QA)

Escala: Alto / Medio-Alto / Medio

| Industria | Viabilidad | Valor QA | Notas de alcance |
|---|---|---|---|
| fintech | Alto | Alto | APIs, onboarding, pagos, antifraude, KYC/AML |
| seguros | Alto | Alto | pólizas, siniestros, reglas de suscripción, compliance |
| salud | Alto | Alto | seguridad del paciente, trazabilidad, privacidad, auditoría |
| retail | Alto | Alto | checkout, inventario, promociones, performance estacional |
| logistica | Alto | Alto | tracking E2E, SLA, integraciones con carriers |
| energia | Medio-Alto | Alto | continuidad operativa, seguridad, normativas técnicas |
| manufactura | Medio-Alto | Alto | calidad de proceso, ERP/MES, control de cambios |
| gobierno | Medio-Alto | Medio-Alto | pliegos, normas y portales heterogéneos |
| educacion | Medio-Alto | Medio-Alto | LMS, accesibilidad, evaluación y evidencia |
| banca (sin BCP) | Medio-Alto | Alto | otras entidades y estándares públicos |
| telecom (sin CONATEL) | Medio | Medio-Alto | operadores y estándares técnicos no-CONATEL |
| agroindustria | Medio | Medio | menor estandarización documental pública |

## Plan de ejecución por olas

1. Ola 1 (impacto rápido): `qa_core`, `fintech`, `seguros`, `salud`, `retail`
2. Ola 2 (profundización): `logistica`, `energia`, `manufactura`, `gobierno`
3. Ola 3 (expansión): `educacion`, `agroindustria`, `banca` (sin BCP), `telecomunicaciones` (sin CONATEL)

## Criterios mínimos para evaluar cada fuente

- Legalidad y términos de uso (robots, copyright, restricciones de redistribución)
- Frescura (fecha de actualización y periodicidad)
- Cobertura temática (riesgo, seguridad, compliance, operación)
- Calidad técnica (HTML estructurado, PDF escaneado, tablas, duplicados)
- Costo de mantenimiento (fragilidad del scraper, cambios de sitio)

## Entregables del pipeline QA

- `qa_core_index`: syllabus + glosario + técnicas + gestión + métricas.
- `exam_index`: preguntas/respuestas ISTQB para práctica y validación.
- `industry_index`: corpus por industria para casos/reglas específicos.

## Siguiente paso técnico inmediato

1. Ejecutar OCR y normalización del corpus CTFL/ISTQB.
2. Aplicar chunking semántico + metadatos (`domain`, `topic`, `source_type`, `lang`, `version`, `confidence_ocr`).
3. Embeddings y smoke test de recuperación (10-20 consultas de control).
