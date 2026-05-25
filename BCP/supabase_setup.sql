-- ============================================================
-- BCP RAG - Supabase pgvector setup
-- Ejecutar en el SQL Editor de tu proyecto Supabase
-- ============================================================

-- 1. Habilitar extensión pgvector
create extension if not exists vector;

-- 2. Tabla de documentos fuente (PDFs scrapeados)
create table if not exists bcp_documents (
  id          uuid primary key default gen_random_uuid(),
  url         text unique not null,
  title       text,
  category    text,           -- 'resolucion', 'circular', 'reglamento', etc.
  published   date,
  filename    text,
  scraped_at  timestamptz default now(),
  indexed_at  timestamptz,
  error       text            -- si falló la indexación
);

-- 3. Tabla de chunks con embeddings
--    voyage-3 genera vectores de 1024 dimensiones
create table if not exists bcp_chunks (
  id           uuid primary key default gen_random_uuid(),
  document_id  uuid references bcp_documents(id) on delete cascade,
  chunk_index  int not null,
  content      text not null,
  token_count  int,
  embedding    vector(1024),
  metadata     jsonb default '{}'::jsonb,  -- página, sección, etc.
  created_at   timestamptz default now()
);

-- 4. Índice HNSW para búsqueda vectorial eficiente
--    (mejor performance que IVFFlat para colecciones medianas)
create index if not exists bcp_chunks_embedding_idx
  on bcp_chunks
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);

-- 5. Índice en document_id para joins rápidos
create index if not exists bcp_chunks_document_id_idx
  on bcp_chunks(document_id);

-- 6. Función RPC para búsqueda semántica
--    Llamada desde Python: supabase.rpc('match_bcp_chunks', {...})
create or replace function match_bcp_chunks(
  query_embedding  vector(1024),
  match_count      int     default 5,
  match_threshold  float   default 0.5,
  filter_category  text    default null
)
returns table (
  id           uuid,
  document_id  uuid,
  content      text,
  metadata     jsonb,
  similarity   float,
  doc_url      text,
  doc_title    text,
  doc_category text
)
language sql stable
as $$
  select
    c.id,
    c.document_id,
    c.content,
    c.metadata,
    1 - (c.embedding <=> query_embedding) as similarity,
    d.url   as doc_url,
    d.title as doc_title,
    d.category as doc_category
  from bcp_chunks c
  join bcp_documents d on d.id = c.document_id
  where
    1 - (c.embedding <=> query_embedding) > match_threshold
    and (filter_category is null or d.category = filter_category)
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

-- 7. Vista útil para monitorear el estado de indexación
create or replace view bcp_indexing_status as
select
  d.category,
  count(distinct d.id)                                     as total_docs,
  count(distinct d.id) filter (where d.indexed_at is not null) as indexed_docs,
  count(distinct d.id) filter (where d.error is not null)  as failed_docs,
  count(c.id)                                              as total_chunks,
  max(d.scraped_at)                                        as last_scrape
from bcp_documents d
left join bcp_chunks c on c.document_id = d.id
group by d.category;
