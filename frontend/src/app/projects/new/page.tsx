'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { createProject } from '@/lib/api'
import Navbar from '@/components/Navbar'

export default function NewProjectPage() {
  const router = useRouter()
  const [name, setName]               = useState('')
  const [industry, setIndustry]       = useState<'banca' | 'telecomunicaciones' | ''>('')
  const [description, setDescription] = useState('')
  const [error, setError]             = useState('')
  const [loading, setLoading]         = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!industry) { setError('Seleccioná una industria'); return }
    setError('')
    setLoading(true)
    try {
      const { project } = await createProject({ name, industry, description: description || undefined })
      router.push(`/projects/${project.id}`)
    } catch (e: any) {
      setError(e.message)
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-xl mx-auto px-6 py-10">
        <div className="mb-6">
          <Link href="/dashboard" className="text-sm text-gray-500 hover:text-gray-700">
            ← Volver al dashboard
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">Nuevo proyecto</h1>
          <p className="text-gray-500 text-sm">
            Creá un proyecto por cliente o sistema a analizar
          </p>
        </div>

        <div className="bg-white border border-gray-200 rounded-2xl p-6">
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Nombre */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nombre del proyecto <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ej: Sistema de Transferencias SIPAP v2"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>

            {/* Industria */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Industria regulatoria <span className="text-red-500">*</span>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setIndustry('banca')}
                  className={`border-2 rounded-xl p-4 text-left transition-colors ${
                    industry === 'banca'
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="text-2xl mb-1">🏦</div>
                  <div className="font-semibold text-gray-900">Banca</div>
                  <div className="text-xs text-gray-500 mt-0.5">Regulaciones BCP</div>
                </button>
                <button
                  type="button"
                  onClick={() => setIndustry('telecomunicaciones')}
                  className={`border-2 rounded-xl p-4 text-left transition-colors ${
                    industry === 'telecomunicaciones'
                      ? 'border-purple-500 bg-purple-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="text-2xl mb-1">📡</div>
                  <div className="font-semibold text-gray-900">Telecom</div>
                  <div className="text-xs text-gray-500 mt-0.5">Regulaciones CONATEL</div>
                </button>
              </div>
            </div>

            {/* Descripción */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Descripción <span className="text-gray-400">(opcional)</span>
              </label>
              <textarea
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Ej: Módulo de pagos del banco XYZ — análisis de cumplimiento SIPAP"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !name || !industry}
              className="w-full bg-brand-600 text-white py-2.5 rounded-lg font-medium hover:bg-brand-700 transition-colors disabled:opacity-50"
            >
              {loading ? 'Creando...' : 'Crear proyecto'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
