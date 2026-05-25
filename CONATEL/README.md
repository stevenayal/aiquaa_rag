# RAG — Regulaciones CONATEL

Pipeline scraping + indexación + consulta semántica para documentos regulatorios
de la Comisión Nacional de Telecomunicaciones del Paraguay (CONATEL).

Comparte la misma base de datos Supabase que el módulo BCP (`rag_documents` / `rag_chunks`),
usando `source = 'conatel'` para separar los documentos.

## Stack

| Componente     | Tecnología                              |
|----------------|-----------------------------------------|
| Scraping       | Python + BeautifulSoup                  |
| Extracción PDF | pdfplumber                              |
| Embeddings     | Voyage AI `voyage-3` (1024 dims)        |
| Vector Store   | Supabase pgvector (`hocryhxndegslzfiwlnx`) |
| Generación     | Anthropic Claude (`claude-sonnet-4`)    |

---

## Setup

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Variables de entorno

```bash
cp .env.example .env
# Editar .env con tus keys reales
```

### 3. Schema de base de datos

Ya aplicado via Supabase MCP. Las tablas son compartidas con BCP:
- `rag_documents` — documentos fuente (field `source = 'conatel'`)
- `rag_chunks` — chunks con embeddings vector(1024)
- `match_rag_chunks` — función RPC para búsqueda semántica
- `rag_indexing_status` — vista de monitoreo

---

## Uso

### Indexación

```bash
# Indexar todas las categorías CONATEL
python indexer.py

# Solo resoluciones
python indexer.py --categories resolucion

# Prueba rápida: 5 documentos
python indexer.py --limit 5

# Re-indexar todo
python indexer.py --reindex
```

### Consultas

```bash
# Modo interactivo (solo CONATEL)
python query.py

# Consulta directa
python query.py "¿Qué requisitos establece CONATEL para operar una red de telefonía móvil?"

# Filtrar por categoría
python query.py "espectro radioeléctrico" --category reglamento

# Búsqueda en ambas fuentes (BCP + CONATEL)
python query.py "normativa AML telecomunicaciones" --source ""
```

---

## Arquitectura

```
conatel.gov.py
    │
    ▼
scraper.py          → Lista de URLs de PDFs por categoría
    │               → Maneja WordPress pagination (?paged=N)
    │               → Visita páginas de entrada para PDFs adjuntos
    ▼
indexer.py
  ├─ Descarga PDF
  ├─ Extrae texto (pdfplumber)
  ├─ Chunking (800 chars, 150 overlap)
  ├─ Embeddings (Voyage AI voyage-3)
  └─ Upsert en Supabase (source='conatel')
         │
         ▼
    rag_documents (source='conatel')
    rag_chunks (vector 1024d, HNSW)

query.py
  ├─ Embed pregunta (Voyage AI, input_type="query")
  ├─ match_rag_chunks RPC (filter_source='conatel')
  ├─ Construir contexto con citas
  └─ Claude genera respuesta fundamentada
```

## Secciones scrapeadas

| Categoría    | URL CONATEL                          |
|--------------|--------------------------------------|
| `resolucion` | `/resoluciones/`                     |
| `reglamento` | `/reglamentos/`                      |
| `normativa`  | `/normativas/` o `/normativa/`       |
| `circular`   | `/circulares/`                       |

## Monitoreo

```sql
-- Estado por fuente y categoría
SELECT * FROM rag_indexing_status WHERE source = 'conatel';

-- Documentos con errores
SELECT url, error, scraped_at
FROM rag_documents
WHERE source = 'conatel' AND error IS NOT NULL;

-- Total de chunks CONATEL
SELECT COUNT(*) FROM rag_chunks c
JOIN rag_documents d ON d.id = c.document_id
WHERE d.source = 'conatel';
```

## Notas sobre el sitio CONATEL

- El sitio usa WordPress; la paginación es `?paged=N`.
- Algunos documentos se publican como adjuntos en posts individuales.
  El scraper visita automáticamente las páginas de entrada para extraerlos.
- Algunos PDFs son escaneados (sin texto). El pipeline los registra con
  `error = 'PDF sin texto extraíble'`. Para OCR agregar `pytesseract`.

## Búsqueda unificada BCP + CONATEL

Desde `query.py` se puede buscar en ambas fuentes simultáneamente
omitiendo `--source` (o pasando `None` en el código). El contexto
incluye el campo `[FRAGMENTO N — BCP/CONATEL]` para identificar la fuente.
