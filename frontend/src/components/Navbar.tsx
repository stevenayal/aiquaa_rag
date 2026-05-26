'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase'

export default function Navbar() {
  const router = useRouter()

  async function handleLogout() {
    const sb = createClient()
    await sb.auth.signOut()
    router.replace('/login')
  }

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <Link href="/dashboard" className="flex items-center gap-2">
        <div className="w-7 h-7 bg-brand-600 rounded-lg flex items-center justify-center">
          <span className="text-white text-xs font-bold">A</span>
        </div>
        <span className="font-semibold text-gray-900">aiquaa RAG</span>
        <span className="text-xs text-gray-400 ml-1">· BCP & CONATEL</span>
      </Link>
      <div className="flex items-center gap-4">
        <Link href="/projects/new" className="text-sm text-brand-600 hover:text-brand-700 font-medium">
          + Nuevo proyecto
        </Link>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          Salir
        </button>
      </div>
    </nav>
  )
}
