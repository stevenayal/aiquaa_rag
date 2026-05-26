'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { getAnalysis, getBddDownloadUrl, getTestPlanDownloadUrl } from '@/lib/api'
import type { Analysis, BddScenario, TestPlan } from '@/lib/supabase'
import Navbar from '@/components/Navbar'

const INDUSTRY_LABELS: Record<string, string> = {
  qa: '🧪 QA',
  fintech: '💳 Fintech',
  seguros: '🛡️ Seguros',
  salud: '🏥 Salud',
  energia: '⚡ Energia',
  retail: '🛒 Retail',
  logistica: '🚚 Logistica',
  gobierno: '🏛️ Gobierno',
  educacion: '🎓 Educacion',
  agroindustria: '🌾 Agroindustria',
  manufactura: '🏭 Manufactura',
  banca: '🏦 Banca',
  telecomunicaciones: '📡 Telecom',
  ambas: '🔀 Multi-industria',
  ninguna: '❓Sin clasificar',
}

type Tab = 'analysis' | 'bdd' | 'testplan'

const PRIORITY_COLOR: Record<string, string> = {
  Alta:  'bg-red-100 text-red-800',
  Media: 'bg-yellow-100 text-yellow-800',
  Baja:  'bg-green-100 text-green-800',
}
const RISK_COLOR: Record<string, string> = {
  'Crítico': 'bg-red-200 text-red-900 font-semibold',
  'Alto':    'bg-orange-100 text-orange-800',
  'Medio':   'bg-yellow-100 text-yellow-800',
  'Bajo':    'bg-green-100 text-green-800',
}

function GherkinBlock({ text }: { text: string }) {
  // Simple syntax highlight via spans
  const highlighted = text
    .replace(/^(Feature:|Background:|Scenario:|Scenario Outline:|Examples:)/gm,
      '<span class="text-purple-400 font-bold">$1</span>')
    .replace(/^\s*(Given|When|Then|And|But)(\s)/gm,
      (m, kw, sp) => `${m.replace(kw, `<span class="text-blue-400 font-semibold">${kw}</span>`)}`)
    .replace(/^(#.*)$/gm, '<span class="text-gray-500">$1</span>')
    .replace(/(&lt;|<)([^>]+)(&gt;|>)/g, '<span class="text-green-400">&lt;$2&gt;</span>')

  return (
    <pre
      className="font-mono text-sm bg-gray-900 text-gray-100 p-4 rounded-lg overflow-auto whitespace-pre-wrap"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  )
}

export default function AnalysisPage() {
  const params = useParams<{ id: string }>()
  const [analysis, setAnalysis]   = useState<Analysis | null>(null)
  const [bddScenarios, setBdd]    = useState<BddScenario[]>([])
  const [testPlan, setTestPlan]   = useState<TestPlan | null>(null)
  const [tab, setTab]             = useState<Tab>('analysis')
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')

  useEffect(() => {
    if (!params.id) return
    getAnalysis(params.id).then(({ analysis, bdd_scenarios, test_plan }) => {
      setAnalysis(analysis)
      setBdd(bdd_scenarios)
      setTestPlan(test_plan)
    }).catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [params.id])

  if (loading) return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="flex justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-600" />
      </div>
    </div>
  )

  if (error || !analysis) return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-3xl mx-auto px-6 py-10">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4">
          {error || 'Análisis no encontrado'}
        </div>
      </div>
    </div>
  )

  const cls = analysis.classification

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <Link href={`/projects/${analysis.project_id}`} className="text-sm text-gray-500 hover:text-gray-700">
            ← Volver al proyecto
          </Link>
          <h1 className="text-xl font-bold text-gray-900 mt-2 line-clamp-3">
            {analysis.requirement_text}
          </h1>
          {cls && (
            <div className="flex flex-wrap gap-2 mt-3">
              <span className="text-xs bg-gray-100 text-gray-600 px-2.5 py-1 rounded-full">
                {INDUSTRY_LABELS[cls.industry] ?? cls.industry}
              </span>
              <span className="text-xs bg-gray-100 text-gray-600 px-2.5 py-1 rounded-full">
                Confianza: {cls.confidence}
              </span>
              {cls.topics?.map((t) => (
                <span key={t} className="text-xs bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full">{t}</span>
              ))}
            </div>
          )}
        </div>

        {/* Descargas */}
        <div className="flex gap-2 mb-6">
          <a
            href={getBddDownloadUrl(params.id)}
            download={`analysis_${params.id.slice(0, 8)}.feature`}
            className="flex items-center gap-1.5 border border-gray-300 rounded-lg px-3 py-2 text-sm hover:bg-gray-50 transition-colors"
          >
            ⬇️ Descargar .feature
          </a>
          <a
            href={getTestPlanDownloadUrl(params.id)}
            download={`test_plan_${params.id.slice(0, 8)}.json`}
            className="flex items-center gap-1.5 border border-gray-300 rounded-lg px-3 py-2 text-sm hover:bg-gray-50 transition-colors"
          >
            ⬇️ Descargar plan.json
          </a>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mb-6 w-fit">
          {([
            { key: 'analysis', label: `📋 Análisis regulatorio` },
            { key: 'bdd',      label: `🧪 BDD (${bddScenarios.length})` },
            { key: 'testplan', label: `📊 Plan de pruebas` },
          ] as { key: Tab; label: string }[]).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-4 py-2 text-sm rounded-md font-medium transition-colors ${
                tab === key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* ── Tab: Análisis ────────────────────────────────────────────── */}
        {tab === 'analysis' && (
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-lg font-semibold text-gray-900">Análisis regulatorio</h2>
              <span className="text-xs text-gray-400">
                {analysis.rag_chunks_used?.length ?? 0} fragmentos usados
              </span>
            </div>
            <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
              {analysis.analysis_narrative || 'Sin narrativa generada.'}
            </div>

            {/* Fuentes usadas */}
            {analysis.rag_chunks_used && analysis.rag_chunks_used.length > 0 && (
              <div className="mt-6 pt-4 border-t border-gray-100">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  📚 Fuentes regulatorias ({analysis.rag_chunks_used.length})
                </h3>
                <div className="space-y-2">
                  {analysis.rag_chunks_used.slice(0, 10).map((chunk, i) => (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      <span className="text-xs font-mono text-gray-400 w-8 text-right">
                        {Math.round((chunk.similarity || 0) * 100)}%
                      </span>
                      <a
                        href={chunk.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-brand-600 hover:underline text-xs flex-1 truncate"
                      >
                        {chunk.title}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Tab: BDD ──────────────────────────────────────────────────── */}
        {tab === 'bdd' && (
          <div className="space-y-4">
            {bddScenarios.length === 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-gray-500">
                Sin escenarios BDD generados.
              </div>
            )}
            {bddScenarios.map((s, i) => (
              <div key={s.id} className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div className="flex items-center gap-3 px-5 py-3 border-b border-gray-100">
                  <span className="text-sm font-semibold text-gray-700">
                    {i + 1}. {s.title}
                  </span>
                  <div className="flex gap-2 ml-auto">
                    <span className={`text-xs px-2.5 py-0.5 rounded-full ${PRIORITY_COLOR[s.priority] ?? 'bg-gray-100 text-gray-600'}`}>
                      {s.priority}
                    </span>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full ${RISK_COLOR[s.regulatory_risk] ?? 'bg-gray-100 text-gray-600'}`}>
                      Riesgo: {s.regulatory_risk}
                    </span>
                  </div>
                </div>
                <div className="p-4">
                  <GherkinBlock text={s.gherkin_text} />
                  {s.normative_refs && s.normative_refs.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {s.normative_refs.map((ref, ri) => (
                        <span key={ri} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded border border-blue-100">
                          📄 {ref}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Tab: Plan de Pruebas ──────────────────────────────────────── */}
        {tab === 'testplan' && testPlan && (
          <div className="space-y-6">
            {/* Summary */}
            <div className="bg-white border border-gray-200 rounded-xl p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-1">
                {testPlan.content.title}
              </h2>
              <p className="text-sm text-gray-600 mt-2">
                {testPlan.content.executive_summary}
              </p>
            </div>

            {/* Tabla de escenarios con impacto */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-100">
                <h3 className="text-sm font-semibold text-gray-900">Escenarios con impacto regulatorio</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 text-gray-600 text-xs">
                      <th className="text-left px-4 py-2.5 font-medium">Escenario</th>
                      <th className="text-left px-4 py-2.5 font-medium">Prioridad</th>
                      <th className="text-left px-4 py-2.5 font-medium">Riesgo</th>
                      <th className="text-left px-4 py-2.5 font-medium">Impacto si falla</th>
                      <th className="text-left px-4 py-2.5 font-medium">Esfuerzo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {testPlan.content.scenarios?.map((s, i) => (
                      <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-900 max-w-xs">{s.scenario_title}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${PRIORITY_COLOR[s.priority] ?? 'bg-gray-100 text-gray-600'}`}>
                            {s.priority}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${RISK_COLOR[s.regulatory_risk] ?? 'bg-gray-100 text-gray-600'}`}>
                            {s.regulatory_risk}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-600 max-w-sm">{s.impact}</td>
                        <td className="px-4 py-3 text-xs text-gray-500 font-mono">{s.estimated_effort}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Matriz de trazabilidad */}
            {testPlan.content.traceability_matrix && testPlan.content.traceability_matrix.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div className="px-5 py-3 border-b border-gray-100">
                  <h3 className="text-sm font-semibold text-gray-900">Matriz de trazabilidad</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 text-gray-600 text-xs">
                        <th className="text-left px-4 py-2.5 font-medium">Fragmento del requerimiento</th>
                        <th className="text-left px-4 py-2.5 font-medium">Regulación</th>
                        <th className="text-left px-4 py-2.5 font-medium">Escenario</th>
                      </tr>
                    </thead>
                    <tbody>
                      {testPlan.content.traceability_matrix.map((row, i) => (
                        <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                          <td className="px-4 py-3 text-xs text-gray-700">{row.requirement_fragment}</td>
                          <td className="px-4 py-3 text-xs text-brand-700 font-medium">{row.regulation}</td>
                          <td className="px-4 py-3 text-xs text-gray-700">{row.scenario_title}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'testplan' && !testPlan && (
          <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-gray-500">
            Sin plan de pruebas generado.
          </div>
        )}
      </main>
    </div>
  )
}
