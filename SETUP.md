# Setup — aiquaa RAG (v2 con multiusuario + BDD)

## Requisitos
- Node 20+
- Python 3.12+
- Cuenta Supabase (proyecto ya existente con rag_documents + rag_chunks)
- Keys: Voyage AI, Anthropic, Supabase

---

## 1. Supabase Auth

En el dashboard de Supabase:
- **Authentication > Providers > Email** → habilitar Email/Password
- (Opcional) Deshabilitar "Confirm email" para dev rápido

## 2. Aplicar migration 002

En Supabase SQL Editor o via CLI:

```sql
-- Copiar y ejecutar el contenido de:
migrations/002_projects_users_bdd.sql
```

Verificar que se crearon las tablas:
```sql
SELECT tablename FROM pg_tables
WHERE schemaname = 'public'
AND tablename IN ('profiles','projects','project_members','analyses','bdd_scenarios','test_plans');
```

## 3. Variables de entorno

```bash
cp .env.example .env
# Editar .env con tus keys reales

cp frontend/.env.local.example frontend/.env.local
# Editar frontend/.env.local con SUPABASE_URL y ANON_KEY
```

## 4. Dev local con Vercel CLI

```bash
# Instalar Vercel CLI si no está
npm i -g vercel

# En el root del proyecto
vercel dev
# → Frontend en http://localhost:3000
# → Python functions en http://localhost:3000/api/*
```

## 5. Instalar deps frontend

```bash
cd frontend
npm install
```

## 6. Verificar Python functions localmente

```bash
# Test classify + questions
curl -X POST http://localhost:3000/api/analyze_questions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <tu_jwt>" \
  -d '{"requirement":"El sistema debe permitir transferencias SIPAP 24/7","project_id":"<uuid>"}'
```

---

## Deploy a Vercel

```bash
# Desde el root
vercel --prod
```

Configurar env vars en Vercel Dashboard > Settings > Environment Variables:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `SUPABASE_ANON_KEY`
- `VOYAGE_API_KEY`
- `ANTHROPIC_API_KEY`

Y para el frontend (prefix `NEXT_PUBLIC_`):
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

---

## Flujo de uso

1. Registrarse en `/login`
2. Crear proyecto en `/projects/new` (elegir Banca o Telecom)
3. Ir al proyecto → "Nuevo análisis"
4. Escribir requerimiento → responder preguntas de clarificación
5. Ver resultado: Análisis + BDD + Plan de Pruebas
6. Descargar `.feature` y `plan.json`
7. Invitar compañeros de equipo en `/projects/{id}/members`
