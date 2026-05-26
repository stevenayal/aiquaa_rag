/**
 * api.ts — Cliente para las Vercel Python Functions
 * Agrega el JWT de Supabase automáticamente en cada request.
 */

import { createClient } from './supabase'

async function getToken(): Promise<string> {
  const sb = createClient()
  const { data } = await sb.auth.getSession()
  return data.session?.access_token ?? ''
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = await getToken()
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  })

  if (!res.ok) {
    let errMsg = `HTTP ${res.status}`
    try {
      const errData = await res.json()
      errMsg = errData.error || errMsg
    } catch {}
    throw new Error(errMsg)
  }

  return res.json()
}

// ── Proyectos ─────────────────────────────────────────────────────────────────

export async function getProjects() {
  return apiFetch<{ projects: import('./supabase').Project[] }>('/api/projects')
}

export async function createProject(data: {
  name: string
  industry: import('./supabase').Industry
  description?: string
}) {
  return apiFetch<{ project: import('./supabase').Project }>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getProject(id: string) {
  return apiFetch<{
    project: import('./supabase').Project
    is_owner: boolean
    members: Array<{ user_id: string; role: string; invited_at: string }>
    analyses: import('./supabase').Analysis[]
  }>(`/api/projects/${id}`)
}

export async function inviteMember(projectId: string, email: string, role = 'viewer') {
  return apiFetch<{ message: string; user_id: string }>(
    `/api/projects/${projectId}/members`,
    {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    },
  )
}

export async function removeMember(projectId: string, userId: string) {
  return apiFetch<{ message: string }>(
    `/api/projects/${projectId}/members/${userId}`,
    { method: 'DELETE' },
  )
}

// ── Análisis ─────────────────────────────────────────────────────────────────

export interface ClarificationQuestion {
  id: string
  text: string
  multi: boolean
  options: string[]
}

export async function getAnalysisQuestions(projectId: string, requirement: string) {
  return apiFetch<{
    classification: { industry: string; topics: string[]; confidence: string } | null
    questions: ClarificationQuestion[]
    has_questions: boolean
  }>('/api/analyze_questions', {
    method: 'POST',
    body: JSON.stringify({ requirement, project_id: projectId }),
  })
}

export async function runAnalysis(
  projectId: string,
  requirement: string,
  answers: Record<string, string[]>,
) {
  return apiFetch<{
    analysis_id: string
    classification: { industry: string; topics: string[]; confidence: string }
    chunks_used: number
    analysis: string
    bdd_scenarios: import('./supabase').BddScenario[]
    test_plan: import('./supabase').TestPlan['content']
  }>('/api/analyze_run', {
    method: 'POST',
    body: JSON.stringify({ requirement, project_id: projectId, answers }),
  })
}

export async function getAnalysis(id: string) {
  return apiFetch<{
    analysis: import('./supabase').Analysis
    bdd_scenarios: import('./supabase').BddScenario[]
    test_plan: import('./supabase').TestPlan | null
  }>(`/api/analyses/${id}`)
}

export function getBddDownloadUrl(analysisId: string) {
  return `/api/analyses/${analysisId}/bdd`
}

export function getTestPlanDownloadUrl(analysisId: string) {
  return `/api/analyses/${analysisId}/test-plan`
}
