-- Migration: add industry + topics classification to RAG documents
-- Applied: 2026-05-25
-- Purpose: classify regulatory docs by industry and topic area
--          so the AI can filter context when analyzing test cases.
--
-- industry: 'banca' | 'telecomunicaciones'
-- topics[]: granular subject tags (transferencias, riesgo, contabilidad, ...)

ALTER TABLE rag_documents
  ADD COLUMN IF NOT EXISTS industry text,
  ADD COLUMN IF NOT EXISTS topics   text[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_rag_documents_industry ON rag_documents(industry);
CREATE INDEX IF NOT EXISTS idx_rag_documents_topics   ON rag_documents USING gin(topics);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_metadata    ON rag_chunks    USING gin(metadata);

-- Populate industry from source
UPDATE rag_documents SET industry = CASE source
  WHEN 'bcp'     THEN 'banca'
  WHEN 'conatel' THEN 'telecomunicaciones'
  ELSE source
END;

-- Auto-classify topics from title + filename keywords
UPDATE rag_documents
SET topics = array_remove(ARRAY[
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%transferencia%','%sipap%','%pago interbanc%']) THEN 'transferencias' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%atm%','%cajero%']) THEN 'atm' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%tarjeta%']) THEN 'tarjetas' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%cuenta corriente%','%cta cte%','%apertura%manten%']) THEN 'cuenta_corriente' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%cuenta basica%','%cuenta básica%']) THEN 'cuenta_basica' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%capital min%','%solvencia%','%patrimoni%']) THEN 'capital' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%casa%cambio%','%corredor%cambio%']) THEN 'cambios' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%auditoria%','%auditoría%']) THEN 'auditoria' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%riesgo%']) THEN 'riesgo' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%fraude%','%prevenci%']) THEN 'fraude_seguridad' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%nube%','%cloud%','%automatizaci%','%tecnolog%']) THEN 'tecnologia' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%firma digital%']) THEN 'firma_digital' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%reporto%']) THEN 'reporto' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%tasa%inter%','%calculo%tasa%']) THEN 'tasas_interes' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%terceri%']) THEN 'tercerizacion' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%cartera%','%credito%','%crédito%','%prestamo%']) THEN 'credito_cartera' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%deposito%','%depósito%','%ahorro%']) THEN 'depositos' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%balance%','%plan de cuentas%','%contab%','%dinamica contable%']) THEN 'contabilidad' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%liquidez%','%encaje%']) THEN 'liquidez' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%lavado%','%blanqueo%','%aml%']) THEN 'aml' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%espectro%','%frecuenci%']) THEN 'espectro' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%concesi%','%licencia%','%habilitacion%']) THEN 'concesiones' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%internet%','%banda ancha%']) THEN 'internet' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%telefon%','%movil%','%celular%']) THEN 'telefonia' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%radiodifusion%','%television%','%televisión%']) THEN 'radiodifusion' END,
  CASE WHEN (title || ' ' || COALESCE(filename,'')) ILIKE ANY(ARRAY['%tarifa%']) THEN 'tarifas' END
], NULL);

-- Reclassify using chunk content for docs still unclassified
-- (run after ocr_processor.py has populated rag_chunks)
WITH doc_text AS (
  SELECT document_id, string_agg(content, ' ' ORDER BY chunk_index) AS txt
  FROM rag_chunks WHERE chunk_index < 3
  GROUP BY document_id
)
UPDATE rag_documents d
SET topics = array_remove(ARRAY[
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%transferencia%','%sipap%','%sistema de pago%']) THEN 'transferencias' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%cajero%automat%','% atm %']) THEN 'atm' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%tarjeta de cr%','%tarjeta de d%']) THEN 'tarjetas' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%cuenta corriente%','%cuentas corrientes%']) THEN 'cuenta_corriente' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%cuenta básica%','%cuenta basica%']) THEN 'cuenta_basica' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%capital mínimo%','%solvencia patrimonial%','%patrimonio neto%']) THEN 'capital' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%casa de cambio%','%casas de cambio%','%corredor de cambio%']) THEN 'cambios' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%auditor%','%informe de audit%']) THEN 'auditoria' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%gestión de riesgo%','%riesgo de crédito%','%riesgo operacional%','%calificación de riesgo%']) THEN 'riesgo' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%fraude%','%prevención del fraude%']) THEN 'fraude_seguridad' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%tecnologías de información%','%mgcti%','%seguridad informátic%','%manual de seguridad%']) THEN 'tecnologia' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%firma digital%','%firma electrónica%']) THEN 'firma_digital' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%operaciones de reporto%']) THEN 'reporto' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%tasa de interés%','%tasas activas%','%tasas pasivas%']) THEN 'tasas_interes' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%tercerización%','%servicios tercerizados%']) THEN 'tercerizacion' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%cartera de crédito%','%venta de cartera%','%microcrédito%']) THEN 'credito_cartera' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%depósito de ahorro%','%depósitos a plazo%','%plazo fijo%']) THEN 'depositos' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%plan de cuenta%','%dinámica contable%','%estados financieros%','%balance general%']) THEN 'contabilidad' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%liquidez%','%encaje legal%']) THEN 'liquidez' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%lavado de dinero%','%lavado de activos%','%financiamiento del terrorismo%']) THEN 'aml' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%gobierno corporativo%','%buen gobierno%']) THEN 'gobierno_corporativo' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%mercado de capitales%','%bono%','%fondo mutuo%','%fideicomiso%']) THEN 'mercado_capitales' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%seguro%','%asegurador%','%corretaje de seguro%']) THEN 'seguros' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%cheque%','%cámara compensadora%']) THEN 'cheques' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%disolución%','%liquidación voluntaria%','%intervención%de%entidad%']) THEN 'disolucion_entidades' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%asesoría financiera%','%agente de bolsa%']) THEN 'asesoria_financiera' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%espectro radioeléctrico%','%frecuencia radioeléctr%','%estación radioeléctrica%']) THEN 'espectro' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%autorización para operar%','%concesión%','%cancela la autorización%']) THEN 'concesiones' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%servicio de internet%','%acceso a internet%','%banda ancha%']) THEN 'internet' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%servicio móvil%','%telefonía móvil%','%red móvil%']) THEN 'telefonia' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%radiodifusión%','%servicio de televisión%','%televisión por cable%']) THEN 'radiodifusion' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%tarifa%del servicio%','%cargo de acceso%','%tarifa máxima%']) THEN 'tarifas' END,
  CASE WHEN dt.txt ILIKE ANY(ARRAY['%interconexión%','%acceso a red%','%red de telecomunicaciones%']) THEN 'interconexion' END
], NULL)
FROM doc_text dt
WHERE dt.document_id = d.id
  AND (d.topics = '{}' OR d.topics IS NULL);

-- Propagate industry + topics to rag_chunks.metadata for chunk-level filtering
UPDATE rag_chunks rc
SET metadata = jsonb_build_object(
  'industry',       d.industry,
  'topics',         to_jsonb(d.topics),
  'source',         d.source,
  'category',       d.category,
  'document_title', d.title,
  'published',      d.published
)
FROM rag_documents d
WHERE rc.document_id = d.id;
