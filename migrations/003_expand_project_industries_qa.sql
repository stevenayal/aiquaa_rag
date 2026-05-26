-- Migration 003: expand industries to QA macro and remaining sectors
-- Applied: 2026-05-25
-- Purpose: permitir proyectos mas alla de banca/telecom y priorizar QA macro.

ALTER TABLE projects
  DROP CONSTRAINT IF EXISTS projects_industry_check;

ALTER TABLE projects
  ADD CONSTRAINT projects_industry_check
  CHECK (
    industry IN (
      'qa',
      'fintech',
      'seguros',
      'salud',
      'energia',
      'retail',
      'logistica',
      'gobierno',
      'educacion',
      'agroindustria',
      'manufactura',
      'banca',
      'telecomunicaciones'
    )
  );

COMMENT ON COLUMN projects.industry IS
'Industria funcional del proyecto. BCP/CONATEL pueden excluirse por fuente aunque exista la industria.';
