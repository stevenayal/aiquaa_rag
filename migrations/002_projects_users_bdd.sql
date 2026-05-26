-- Migration 002: Multi-user projects + BDD analysis storage
-- Applied: 2026-05-25
-- Purpose: proyecto por industria, multiusuario con RLS,
--          guardado de análisis, BDD y planes de prueba.

-- ─────────────────────────────────────────────────────────────────
-- 1. Perfiles de usuario (linked a auth.users)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
  id           uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name text,
  avatar_url   text,
  created_at   timestamptz DEFAULT now()
);

-- Auto-crear perfil al registrarse
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO profiles(id, display_name)
  VALUES (NEW.id, COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)))
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ─────────────────────────────────────────────────────────────────
-- 2. Proyectos con categoría de industria
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  description text,
  industry    text NOT NULL CHECK (industry IN ('banca', 'telecomunicaciones')),
  owner_id    uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_owner_id  ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_industry   ON projects(industry);

-- ─────────────────────────────────────────────────────────────────
-- 3. Miembros del proyecto (owner + invitados)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS project_members (
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id    uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role       text NOT NULL DEFAULT 'viewer'
             CHECK (role IN ('admin', 'editor', 'viewer')),
  invited_by uuid REFERENCES auth.users(id),
  invited_at timestamptz DEFAULT now(),
  PRIMARY KEY (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_project_members_user_id ON project_members(user_id);

-- ─────────────────────────────────────────────────────────────────
-- 4. Análisis de requerimientos
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analyses (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id            uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id               uuid NOT NULL REFERENCES auth.users(id),
  requirement_text      text NOT NULL,
  clarification_answers jsonb DEFAULT '{}',  -- {q_id: [selected_options]}
  classification        jsonb,               -- {industry, topics, confidence, search_query}
  rag_chunks_used       jsonb DEFAULT '[]',  -- [{id, score, title, url}]
  analysis_narrative    text,
  created_at            timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analyses_project_id ON analyses(project_id);
CREATE INDEX IF NOT EXISTS idx_analyses_user_id    ON analyses(user_id);

-- ─────────────────────────────────────────────────────────────────
-- 5. Escenarios BDD generados
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bdd_scenarios (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id      uuid NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  title            text NOT NULL,
  gherkin_text     text NOT NULL,
  priority         text CHECK (priority IN ('Alta', 'Media', 'Baja')),
  regulatory_risk  text CHECK (regulatory_risk IN ('Crítico', 'Alto', 'Medio', 'Bajo')),
  normative_refs   text[] DEFAULT '{}',
  created_at       timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bdd_analysis_id ON bdd_scenarios(analysis_id);

-- ─────────────────────────────────────────────────────────────────
-- 6. Planes de prueba
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS test_plans (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id uuid NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  title       text NOT NULL,
  content     jsonb NOT NULL,  -- estructura completa: executive_summary, scenarios, matrix
  created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_test_plans_analysis_id ON test_plans(analysis_id);

-- ─────────────────────────────────────────────────────────────────
-- 7. RLS — Row Level Security
-- ─────────────────────────────────────────────────────────────────

-- profiles: cada usuario ve solo su perfil
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "profiles_own"
  ON profiles FOR ALL
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

-- projects: owner + miembros del proyecto
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY "projects_select"
  ON projects FOR SELECT
  USING (
    owner_id = auth.uid()
    OR id IN (
      SELECT project_id FROM project_members WHERE user_id = auth.uid()
    )
  );
CREATE POLICY "projects_insert"
  ON projects FOR INSERT
  WITH CHECK (owner_id = auth.uid());
CREATE POLICY "projects_update"
  ON projects FOR UPDATE
  USING (owner_id = auth.uid())
  WITH CHECK (owner_id = auth.uid());
CREATE POLICY "projects_delete"
  ON projects FOR DELETE
  USING (owner_id = auth.uid());

-- project_members: visible para owner y el mismo miembro
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY "members_select"
  ON project_members FOR SELECT
  USING (
    user_id = auth.uid()
    OR project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
    )
  );
CREATE POLICY "members_insert"
  ON project_members FOR INSERT
  WITH CHECK (
    project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
    )
  );
CREATE POLICY "members_delete"
  ON project_members FOR DELETE
  USING (
    project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
    )
  );

-- analyses: heredan visibilidad del proyecto
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION user_can_access_project(pid uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER AS $$
  SELECT EXISTS (
    SELECT 1 FROM projects WHERE id = pid AND owner_id = auth.uid()
    UNION ALL
    SELECT 1 FROM project_members WHERE project_id = pid AND user_id = auth.uid()
  );
$$;

CREATE POLICY "analyses_select"
  ON analyses FOR SELECT
  USING (user_can_access_project(project_id));
CREATE POLICY "analyses_insert"
  ON analyses FOR INSERT
  WITH CHECK (user_can_access_project(project_id) AND user_id = auth.uid());
CREATE POLICY "analyses_delete"
  ON analyses FOR DELETE
  USING (user_id = auth.uid());

-- bdd_scenarios: via analysis_id → project
ALTER TABLE bdd_scenarios ENABLE ROW LEVEL SECURITY;
CREATE POLICY "bdd_select"
  ON bdd_scenarios FOR SELECT
  USING (
    analysis_id IN (
      SELECT id FROM analyses WHERE user_can_access_project(project_id)
    )
  );
CREATE POLICY "bdd_insert"
  ON bdd_scenarios FOR INSERT
  WITH CHECK (
    analysis_id IN (
      SELECT id FROM analyses WHERE user_can_access_project(project_id)
    )
  );

-- test_plans: igual que bdd_scenarios
ALTER TABLE test_plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY "test_plans_select"
  ON test_plans FOR SELECT
  USING (
    analysis_id IN (
      SELECT id FROM analyses WHERE user_can_access_project(project_id)
    )
  );
CREATE POLICY "test_plans_insert"
  ON test_plans FOR INSERT
  WITH CHECK (
    analysis_id IN (
      SELECT id FROM analyses WHERE user_can_access_project(project_id)
    )
  );

-- ─────────────────────────────────────────────────────────────────
-- 8. Vista útil: resumen de proyecto con conteos
-- ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW project_summary AS
SELECT
  p.id,
  p.name,
  p.description,
  p.industry,
  p.owner_id,
  p.created_at,
  COUNT(DISTINCT pm.user_id) AS member_count,
  COUNT(DISTINCT a.id)       AS analysis_count
FROM projects p
LEFT JOIN project_members pm ON pm.project_id = p.id
LEFT JOIN analyses        a  ON a.project_id  = p.id
GROUP BY p.id, p.name, p.description, p.industry, p.owner_id, p.created_at;
