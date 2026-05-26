'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { getProject } from '@/lib/api'
import type { Project, Analysis } from '@/lib/supabase'
import Navbar from '@/components/Navbar'

const INDUSTRY_LABELS: Record<string, string> = {
  banca:              '🏦 Banca (BCP)',
  telecomunicaciones: '📡 Telecom (CONATEL)',
}

const RISK_COLORS: Record<string, string> = {
  'Crítico': 'bg-red-100 text-red-800',
  'Alto':    'bg-orange-100 text-orange-800',
  'Medio':   'bg-yellow-100 text-yellow-800',
  'Bajo':    'bg-green-100 text-green-800',
}

export default function ProjectPage() {
  const router = useRouter()
  const params = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [isOwner, setIsOwner]   = useState(false)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  useEffect(() => {
    if (!params.id) return
    loadProject(params.id)
  }, [params.id])

  async function loadProject(id: string) {
    try {
      const data = await getProject(id)
      setProject(data.project)
      setAnalyses(data.analyses)
      setIsOwner(data.is_owner)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="flex justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-600" />
      </div>
    </div>
  )

  if (error || !project) return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-3xl mx-auto px-6 py-10">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4">
          {error || 'Proyecto no encontrado'}
        </div>
        <Link href="/dashboard" className="text-sm text-brand-600 mt-4 inline-block">
          ← Volver al dashboard
        </Link>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Header proyecto */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <Link href="/dashboard" className="text-sm text-gray-500 hover:text-gray-700">
              ← Dashboard
            </Link>
            <div className="flex items-center gap-3 mt-2">
              <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
              <span className="text-sm text-gray-500 bg-gray-100 px-2.5 py-1 rounded-full">
                {INDUSTRY_LABELS[project.industry] ?? project.industry}
              </span>
            </div>
            {project.description && (
              <p className="text-gray-500 text-sm mt-1">{project.description}</p>
            )}
          </div>
          <div className="flex gap-2">
            {isOwner && (
              <Link
                href={`/projects/${project.id}/members`}
                className="text-sm border border-gray-300 rounded-lg px-3 py-2 hover:bg-gray-50"
              >
                👥 Miembros
              </Link>
            )}
            <Link
              href={`/projects/${project.id}/analyze`}
              className="bg-brand-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-brand-700 font-medium"
            >
              + Nuevo análisis
            </Link>
          </div>
        </div>

        {/* Lista de análisis */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Análisis ({analyses.length})
          </h2>

          {analyses.length === 0 && (
            <div className="text-center py-16 bg-white rounded-xl border border-gray-200">
              <div className="text-4xl mb-3">🔍</div>
              <h3 className="font-semibold text-gray-700 mb-1">Sin análisis</h3>
              <p className="text-gray-500 text-sm mb-4">
                Analizá un requerimiento para generar casos BDD y plan de pruebas
              </p>
              <Link
                href={`/projects/${project.id}/analyze`}
                className="inline-block bg-brand-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Nuevo análisis
              </Link>
            </div>
          )}

          <div className="space-y-3">
            {analyses.map((a) => {
              const cls = a.classification
              return (
                <Link
                  key={a.id}
                  href={`/analyses/${a.id}`}
                  className="flex items-start justify-between bg-white border border-gray-200 rounded-xl p-4 hover:shadow-sm hover:border-brand-200 transition-all group"
                >
                  <div className="flex-1 min-w-0 mr-4">
                    <p className="text-sm font-medium text-gray-900 line-clamp-2 group-hover:text-brand-700">
                      {a.requirement_text}
                    </p>
                    {cls && (
                      <div className="flex gap-1.5 flex-wrap mt-2">
                        {cls.topics?.slice(0, 4).map((t) => (
                          <span key={t} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-xs text-gray-400">
                      {new Date(a.created_at).toLocaleDateString('es-PY')}
                    </p>
                    <p className="text-xs text-brand-600 mt-1 font-medium">Ver análisis →</p>
                  </div>
                </Link>
              )
            })}
          </div>
        </div>
      </main>
    </div>
  )
}
