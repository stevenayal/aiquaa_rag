'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { createClient } from '@/lib/supabase'
import { getProjects } from '@/lib/api'
import type { Project } from '@/lib/supabase'
import Navbar from '@/components/Navbar'

const INDUSTRY_LABELS: Record<string, { label: string; color: string }> = {
  qa:                 { label: '🧪 QA',                color: 'bg-emerald-100 text-emerald-800' },
  fintech:            { label: '💳 Fintech',           color: 'bg-cyan-100 text-cyan-800' },
  seguros:            { label: '🛡️ Seguros',          color: 'bg-sky-100 text-sky-800' },
  salud:              { label: '🏥 Salud',             color: 'bg-rose-100 text-rose-800' },
  energia:            { label: '⚡ Energia',           color: 'bg-amber-100 text-amber-800' },
  retail:             { label: '🛒 Retail',            color: 'bg-orange-100 text-orange-800' },
  logistica:          { label: '🚚 Logistica',         color: 'bg-lime-100 text-lime-800' },
  gobierno:           { label: '🏛️ Gobierno',         color: 'bg-slate-100 text-slate-800' },
  educacion:          { label: '🎓 Educacion',         color: 'bg-indigo-100 text-indigo-800' },
  agroindustria:      { label: '🌾 Agroindustria',     color: 'bg-green-100 text-green-800' },
  manufactura:        { label: '🏭 Manufactura',       color: 'bg-zinc-100 text-zinc-800' },
  banca:            { label: '🏦 Banca',            color: 'bg-blue-100 text-blue-800' },
  telecomunicaciones: { label: '📡 Telecom',         color: 'bg-violet-100 text-violet-800' },
}

export default function DashboardPage() {
  const router = useRouter()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  useEffect(() => {
    const sb = createClient()
    sb.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.replace('/login')
        return
      }
      loadProjects()
    })
  }, [router])

  async function loadProjects() {
    try {
      const data = await getProjects()
      setProjects(data.projects)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Mis proyectos</h1>
            <p className="text-gray-500 text-sm mt-0.5">
              Cada proyecto agrupa análisis de requerimientos regulatorios
            </p>
          </div>
          <Link
            href="/projects/new"
            className="bg-brand-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            + Nuevo proyecto
          </Link>
        </div>

        {loading && (
          <div className="flex justify-center py-16">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-600" />
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 text-sm">
            {error}
          </div>
        )}

        {!loading && projects.length === 0 && (
          <div className="text-center py-20 bg-white rounded-2xl border border-gray-200">
            <div className="text-4xl mb-3">📂</div>
            <h3 className="text-lg font-semibold text-gray-700 mb-1">Sin proyectos</h3>
            <p className="text-gray-500 text-sm mb-4">
              Creá tu primer proyecto para empezar a analizar requerimientos
            </p>
            <Link
              href="/projects/new"
              className="inline-block bg-brand-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-brand-700"
            >
              Crear proyecto
            </Link>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => {
            const ind = INDUSTRY_LABELS[p.industry] ?? { label: p.industry, color: 'bg-gray-100 text-gray-700' }
            return (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="bg-white border border-gray-200 rounded-xl p-5 hover:shadow-md hover:border-brand-300 transition-all group"
              >
                <div className="flex items-start justify-between mb-3">
                  <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${ind.color}`}>
                    {ind.label}
                  </span>
                </div>
                <h3 className="font-semibold text-gray-900 group-hover:text-brand-700 mb-1">
                  {p.name}
                </h3>
                {p.description && (
                  <p className="text-gray-500 text-sm line-clamp-2">{p.description}</p>
                )}
                <p className="text-xs text-gray-400 mt-3">
                  Creado {new Date(p.created_at).toLocaleDateString('es-PY')}
                </p>
              </Link>
            )
          })}
        </div>
      </main>
    </div>
  )
}
