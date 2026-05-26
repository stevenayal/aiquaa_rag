'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { getProject, inviteMember, removeMember } from '@/lib/api'
import type { Project } from '@/lib/supabase'
import Navbar from '@/components/Navbar'

interface Member {
  user_id: string
  role: string
  invited_at: string
}

export default function MembersPage() {
  const params    = useParams<{ id: string }>()
  const projectId = params.id

  const [project, setProject]   = useState<Project | null>(null)
  const [members, setMembers]   = useState<Member[]>([])
  const [isOwner, setIsOwner]   = useState(false)
  const [loading, setLoading]   = useState(true)
  const [email, setEmail]       = useState('')
  const [role, setRole]         = useState<'admin' | 'editor' | 'viewer'>('viewer')
  const [inviting, setInviting] = useState(false)
  const [error, setError]       = useState('')
  const [success, setSuccess]   = useState('')

  useEffect(() => {
    if (!projectId) return
    getProject(projectId).then(({ project, members, is_owner }) => {
      setProject(project)
      setMembers(members)
      setIsOwner(is_owner)
    }).catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [projectId])

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')
    setInviting(true)
    try {
      const res = await inviteMember(projectId, email, role)
      setSuccess(res.message)
      setEmail('')
      // Recargar miembros
      const data = await getProject(projectId)
      setMembers(data.members)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setInviting(false)
    }
  }

  async function handleRemove(userId: string) {
    if (!confirm('¿Remover este miembro?')) return
    try {
      await removeMember(projectId, userId)
      setMembers((m) => m.filter((x) => x.user_id !== userId))
    } catch (e: any) {
      setError(e.message)
    }
  }

  const ROLE_LABELS: Record<string, string> = {
    admin:  '👑 Admin',
    editor: '✏️ Editor',
    viewer: '👁️ Viewer',
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-2xl mx-auto px-6 py-10">
        <div className="mb-6">
          <Link href={`/projects/${projectId}`} className="text-sm text-gray-500 hover:text-gray-700">
            ← Volver al proyecto
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">
            Miembros — {project?.name}
          </h1>
          <p className="text-gray-500 text-sm">
            Solo los miembros invitados pueden ver este proyecto.
          </p>
        </div>

        {!isOwner && (
          <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 text-sm rounded-lg p-3 mb-4">
            Solo el owner puede gestionar miembros.
          </div>
        )}

        {/* Invitar */}
        {isOwner && (
          <div className="bg-white border border-gray-200 rounded-2xl p-6 mb-6">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Invitar miembro</h2>
            <form onSubmit={handleInvite} className="space-y-4">
              <div className="flex gap-3">
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="correo@empresa.com"
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as any)}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  type="submit"
                  disabled={inviting}
                  className="bg-brand-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
                >
                  {inviting ? '...' : 'Invitar'}
                </button>
              </div>
              {error  && <p className="text-red-600 text-sm">{error}</p>}
              {success && <p className="text-green-600 text-sm">{success}</p>}
            </form>
          </div>
        )}

        {/* Lista de miembros */}
        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">
              Miembros ({members.length})
            </h2>
          </div>
          {members.length === 0 ? (
            <div className="px-5 py-8 text-center text-gray-400 text-sm">
              Sin miembros invitados. Solo vos como owner podés ver este proyecto.
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {members.map((m) => (
                <div key={m.user_id} className="flex items-center justify-between px-5 py-3">
                  <div>
                    <p className="text-sm font-mono text-gray-700">{m.user_id.slice(0, 8)}...</p>
                    <p className="text-xs text-gray-400">
                      Invitado {new Date(m.invited_at).toLocaleDateString('es-PY')}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs bg-gray-100 text-gray-600 px-2.5 py-1 rounded-full">
                      {ROLE_LABELS[m.role] ?? m.role}
                    </span>
                    {isOwner && (
                      <button
                        onClick={() => handleRemove(m.user_id)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remover
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
