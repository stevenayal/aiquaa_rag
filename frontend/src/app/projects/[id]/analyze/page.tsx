'use client'

import { useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { getAnalysisQuestions, runAnalysis } from '@/lib/api'
import type { ClarificationQuestion } from '@/lib/api'
import Navbar from '@/components/Navbar'

type Step = 'input' | 'questions' | 'analyzing' | 'done'

export default function AnalyzePage() {
  const params   = useParams<{ id: string }>()
  const router   = useRouter()
  const projectId = params.id

  const [step, setStep]               = useState<Step>('input')
  const [requirement, setRequirement] = useState('')
  const [questions, setQuestions]     = useState<ClarificationQuestion[]>([])
  const [answers, setAnswers]         = useState<Record<string, string[]>>({})
  const [error, setError]             = useState('')
  const [analysisId, setAnalysisId]   = useState('')

  // ── Step 1: enviar requerimiento → obtener preguntas ─────────────────
  async function handleRequirementSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!requirement.trim()) return
    setError('')
    setStep('questions') // Mostrar spinner mientras clasifica

    try {
      const data = await getAnalysisQuestions(projectId, requirement)
      setQuestions(data.questions)
      if (!data.has_questions) {
        // Sin preguntas → ir directo al análisis
        await runFullAnalysis({})
      }
      // Si hay preguntas → quedarse en 'questions' para que el user responda
    } catch (e: any) {
      setError(e.message)
      setStep('input')
    }
  }

  // ── Step 2: responder preguntas y lanzar análisis ─────────────────────
  async function handleAnswersSubmit(e: React.FormEvent) {
    e.preventDefault()
    await runFullAnalysis(answers)
  }

  async function runFullAnalysis(answersToSend: Record<string, string[]>) {
    setError('')
    setStep('analyzing')
    try {
      const data = await runAnalysis(projectId, requirement, answersToSend)
      setAnalysisId(data.analysis_id)
      setStep('done')
    } catch (e: any) {
      setError(e.message)
      setStep('questions')
    }
  }

  // ── Toggle de respuesta (multi o single) ─────────────────────────────
  function toggleAnswer(qId: string, option: string, multi: boolean) {
    setAnswers((prev) => {
      const current = prev[qId] ?? []
      if (multi) {
        return {
          ...prev,
          [qId]: current.includes(option)
            ? current.filter((o) => o !== option)
            : [...current, option],
        }
      } else {
        return { ...prev, [qId]: [option] }
      }
    })
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-2xl mx-auto px-6 py-10">
        <div className="mb-6">
          <Link href={`/projects/${projectId}`} className="text-sm text-gray-500 hover:text-gray-700">
            ← Volver al proyecto
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">Nuevo análisis regulatorio</h1>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-8">
          {[
            { key: 'input',     label: '1. Requerimiento' },
            { key: 'questions', label: '2. Aclaraciones' },
            { key: 'analyzing', label: '3. Analizando' },
            { key: 'done',      label: '4. Resultado' },
          ].map((s, i) => {
            const order = ['input', 'questions', 'analyzing', 'done']
            const active  = s.key === step
            const done    = order.indexOf(step) > order.indexOf(s.key)
            return (
              <div key={s.key} className="flex items-center gap-2">
                {i > 0 && <div className="w-8 h-px bg-gray-300" />}
                <div className={`flex items-center gap-1.5 text-xs font-medium transition-colors ${
                  active ? 'text-brand-700' : done ? 'text-green-600' : 'text-gray-400'
                }`}>
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs ${
                    active ? 'bg-brand-600 text-white' : done ? 'bg-green-500 text-white' : 'bg-gray-200'
                  }`}>
                    {done ? '✓' : i + 1}
                  </div>
                  <span className="hidden sm:block">{s.label}</span>
                </div>
              </div>
            )
          })}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 mb-4">
            {error}
          </div>
        )}

        {/* ── STEP 1: Input requerimiento ─────────────────────────────── */}
        {step === 'input' && (
          <form onSubmit={handleRequirementSubmit} className="bg-white border border-gray-200 rounded-2xl p-6 space-y-4">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2">
                Describí el requerimiento del sistema
              </label>
              <p className="text-xs text-gray-500 mb-3">
                Escribí en lenguaje natural. El sistema detectará la industria regulatoria y los temas aplicables.
              </p>
              <textarea
                required
                rows={5}
                value={requirement}
                onChange={(e) => setRequirement(e.target.value)}
                placeholder="Ej: El sistema debe permitir transferencias SIPAP 24/7 con autenticación de doble factor. El monto máximo por operación es de G. 50.000.000 y debe generar comprobante con número de operación SPI..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
              />
            </div>
            <button
              type="submit"
              disabled={!requirement.trim()}
              className="w-full bg-brand-600 text-white py-2.5 rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
            >
              Siguiente →
            </button>
          </form>
        )}

        {/* ── STEP 2: Preguntas de clarificación ──────────────────────── */}
        {step === 'questions' && questions.length > 0 && (
          <form onSubmit={handleAnswersSubmit} className="bg-white border border-gray-200 rounded-2xl p-6 space-y-6">
            <div>
              <h2 className="text-base font-semibold text-gray-900 mb-1">
                Aclaraciones para mejorar el análisis
              </h2>
              <p className="text-xs text-gray-500">
                Estas respuestas ayudan a enfocar la búsqueda regulatoria. Podés omitir si no estás seguro.
              </p>
            </div>

            {questions.map((q) => {
              const selected = answers[q.id] ?? []
              return (
                <div key={q.id} className="space-y-2">
                  <label className="block text-sm font-medium text-gray-800">
                    {q.text}
                    {q.multi && <span className="text-xs text-gray-400 ml-1">(podés seleccionar varios)</span>}
                  </label>
                  <div className="grid gap-2">
                    {q.options.map((opt) => {
                      const isSelected = selected.includes(opt)
                      return (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => toggleAnswer(q.id, opt, q.multi)}
                          className={`text-left text-sm px-4 py-2.5 rounded-lg border-2 transition-colors ${
                            isSelected
                              ? 'border-brand-500 bg-brand-50 text-brand-800'
                              : 'border-gray-200 hover:border-gray-300 text-gray-700'
                          }`}
                        >
                          <span className={`mr-2 ${q.multi ? 'inline-block w-4 h-4 border rounded border-current text-center text-xs leading-4' : ''}`}>
                            {q.multi ? (isSelected ? '✓' : '') : (isSelected ? '●' : '○')}
                          </span>
                          {opt}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}

            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => runFullAnalysis({})}
                className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm hover:bg-gray-50 transition-colors"
              >
                Omitir aclaraciones
              </button>
              <button
                type="submit"
                className="flex-1 bg-brand-600 text-white py-2.5 rounded-lg font-medium hover:bg-brand-700 transition-colors"
              >
                Analizar →
              </button>
            </div>
          </form>
        )}

        {/* ── STEP 3: Analizando ──────────────────────────────────────── */}
        {step === 'analyzing' && (
          <div className="bg-white border border-gray-200 rounded-2xl p-10 text-center space-y-4">
            <div className="inline-flex items-center justify-center w-14 h-14 bg-brand-50 rounded-full mb-2">
              <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-brand-600" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900">Analizando regulaciones...</h2>
            <div className="space-y-1 text-sm text-gray-500">
              <p>🔍 Buscando fragmentos regulatorios relevantes</p>
              <p>⚖️ Evaluando normas BCP / CONATEL</p>
              <p>📝 Generando escenarios BDD y plan de pruebas</p>
            </div>
            <p className="text-xs text-gray-400 mt-4">Esto puede tomar 15-30 segundos</p>
          </div>
        )}

        {/* ── STEP 4: Done ────────────────────────────────────────────── */}
        {step === 'done' && analysisId && (
          <div className="bg-white border border-green-200 rounded-2xl p-8 text-center space-y-4">
            <div className="text-5xl">✅</div>
            <h2 className="text-xl font-bold text-gray-900">¡Análisis completado!</h2>
            <p className="text-gray-500 text-sm">
              Se generaron escenarios BDD y el plan de pruebas regulatorio.
            </p>
            <div className="flex flex-col gap-3 mt-2">
              <Link
                href={`/analyses/${analysisId}`}
                className="bg-brand-600 text-white py-3 rounded-xl font-medium hover:bg-brand-700 transition-colors"
              >
                Ver resultados →
              </Link>
              <button
                onClick={() => {
                  setStep('input')
                  setRequirement('')
                  setQuestions([])
                  setAnswers({})
                  setAnalysisId('')
                }}
                className="border border-gray-300 text-gray-700 py-2.5 rounded-xl text-sm hover:bg-gray-50"
              >
                Analizar otro requerimiento
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
