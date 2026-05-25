# RAG — Regulaciones BCP

Pipeline de scraping + indexación + consulta semántica para documentos regulatorios
del Banco Central del Paraguay.

## Stack

| Componente     | Tecnología                              |
|----------------|-----------------------------------------|
| Scraping       | Python + BeautifulSoup                  |
| Extracción PDF | pdfplumber                              |
| Embeddings     | Voyage AI `voyage-3` (1024 dims)        |
| Vector Store   | Supabase pgvector                       |
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

#### Voyage AI
Registrate en https://dash.voyageai.com — tiene free tier generoso (200M tokens/mes).

#### Supabase
Usá la `service_role` key (no la `anon`), porque necesitás permisos de escritura.

### 3. Inicializar Supabase

Ejecutar `supabase_setup.sql` en el SQL Editor de tu proyecto:

```sql
-- El archivo habilita pgvector, crea las tablas, índice HNSW
-- y la función RPC match_bcp_chunks
```

---

## Uso

### Indexación completa

```bash
# Indexar todas las categorías
python indexer.py

# Solo resoluciones y circulares
python indexer.py --categories resolucion circular

# Prueba rápida: solo 5 documentos
python indexer.py --limit 5

# Re-indexar todo (fuerza actualización)
python indexer.py --reindex
```

### Consultas

```bash
# Modo interactivo (recomendado para explorar)
python query.py

# Consulta directa
python query.py "¿Qué límites establece el BCP para el encaje legal?"

# Filtrar por categoría
python query.py "requisitos de capital mínimo" --category resolucion

# Ajustar sensibilidad
python query.py "normativa AML" --top-k 8 --threshold 0.4
```

---

## Arquitectura

```
bcp.gov.py
    │
    ▼
scraper.py          → Lista de URLs de PDFs por categoría
    │
    ▼
indexer.py
  ├─ Descarga PDF
  ├─ Extrae texto (pdfplumber)
  ├─ Chunking (800 chars, 150 overlap)
  ├─ Embeddings (Voyage AI voyage-3)
  └─ Upsert en Supabase
         │
         ▼
    bcp_documents
    bcp_chunks (vector 1024d, índice HNSW)

query.py
  ├─ Embed pregunta (Voyage AI, input_type="query")
  ├─ match_bcp_chunks RPC (cosine similarity)
  ├─ Construir contexto con citas
  └─ Claude genera respuesta fundamentada
```

## Monitoreo

```sql
-- Ver estado de indexación por categoría
SELECT * FROM bcp_indexing_status;

-- Documentos con errores
SELECT url, error, scraped_at
FROM bcp_documents
WHERE error IS NOT NULL;

-- Total de chunks
SELECT COUNT(*) FROM bcp_chunks;
```

## Notas sobre el sitio BCP

- El sitio `bcp.gov.py` tiene paginación en sus listados de regulaciones.
- Algunos PDFs son **escaneados** (sin capa de texto). El pipeline los registra
  con `error = 'PDF sin texto extraíble'`. Para OCR, se puede agregar
  `pytesseract` como paso adicional.
- Se recomienda ejecutar el indexador periódicamente (ej. cron semanal)
  para capturar nuevas resoluciones.

## Extensiones posibles

- **OCR**: integrar `pytesseract` + `pdf2image` para PDFs escaneados
- **API REST**: exponer `query.py` como endpoint FastAPI
- **Scheduler**: cron con `APScheduler` para indexación automática
- **Frontend**: integrar con el backend NestJS de Aiquaa como módulo de compliance
