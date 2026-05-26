import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'aiquaa RAG — Análisis Regulatorio',
  description: 'Análisis de requerimientos contra regulaciones BCP y CONATEL con IA',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="es">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        {children}
      </body>
    </html>
  )
}
