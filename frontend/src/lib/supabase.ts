import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  )
}

// Tipos de las tablas nuevas
export type Industry = 'banca' | 'telecomunicaciones'
export type MemberRole = 'admin' | 'editor' | 'viewer'
export type Priority = 'Alta' | 'Media' | 'Baja'
export type RegRisk = 'Crítico' | 'Alto' | 'Medio' | 'Bajo'

export interface Project {
  id: string
  name: string
  description: string | null
  industry: Industry
  owner_id: string
  created_at: string
}

export interface Analysis {
  id: string
  project_id: string
  user_id: string
  requirement_text: string
  clarification_answers: Record<string, string[]>
  classification: {
    industry: string
    topics: string[]
    confidence: string
  } | null
  rag_chunks_used: Array<{ title: string; url: string; similarity: number }>
  analysis_narrative: string | null
  created_at: string
}

export interface BddScenario {
  id: string
  analysis_id: string
  title: string
  gherkin_text: string
  priority: Priority
  regulatory_risk: RegRisk
  normative_refs: string[]
  created_at: string
}

export interface TestPlan {
  id: string
  analysis_id: string
  title: string
  content: {
    title: string
    executive_summary: string
    scenarios: Array<{
      scenario_title: string
      priority: Priority
      regulatory_risk: RegRisk
      impact: string
      normative_refs: string[]
      estimated_effort: string
    }>
    traceability_matrix: Array<{
      requirement_fragment: string
      regulation: string
      scenario_title: string
    }>
  }
  created_at: string
}
