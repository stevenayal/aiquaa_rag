# aiquaa_rag — Pipeline RAG de Regulaciones Paraguayas

Sistema de indexación y consulta RAG (Retrieval-Augmented Generation) para regulaciones de organismos gubernamentales de Paraguay. Actualmente cubre **BCP** (Banco Central del Paraguay) y **CONATEL** (Comisión Nacional de Telecomunicaciones).

---

## Arquitectura general

```
Sitio web (BCP / CONATEL)
        │
        ▼
   scraper.py          ← descarga y extrae links a PDFs
        │
        ▼
   indexer.py          ← descarga PDFs, extrae texto (pdfplumber),
        │                 divide en chunks, genera embeddings (Voyage AI)
        ▼
   Supabase (pgvector) ← almacena documentos + chunks con vectores 1024 dims
        │
        ▼
   query.py            ← búsqueda semántica + respuesta con Claude (Anthropic)
```

---

## Base de datos (Supabase)

**Proyecto:** `hocryhxndegslzfiwlnx` — `https://hocryhxndegslzfiwlnx.supabase.co`

### Tablas

#### `rag_documents`
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | uuid PK | ID único |
| `source` | text | `'bcp'` o `'conatel'` |
| `url` | text UNIQUE | URL del PDF original |
| `title` | text | Título del documento |
| `category` | text | Tipo de norma (ver abajo) |
| `published` | date | Fecha de publicación |
| `filename` | text | Nombre del archivo PDF |
| `indexed_at` | timestamptz | Cuándo fue indexado |
| `error` | text | Error si falló la indexación |

#### `rag_chunks`
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | uuid PK | ID único |
| `document_id` | uuid FK | Referencia a `rag_documents` |
| `chunk_index` | int | Posición del chunk en el doc |
| `content` | text | Texto del chunk |
| `token_count` | int | Aprox. tokens (chars / 4) |
| `embedding` | vector(1024) | Embedding Voyage AI (NULL si `--no-embed`) |
| `metadata` | jsonb | Metadatos adicionales |

### Función RPC

```sql
match_rag_chunks(
  query_embedding  vector(1024),
  match_count      int,
  match_threshold  float,
  filter_source    text,    -- 'bcp', 'conatel', o NULL para ambos
  filter_category  text     -- 'resolucion', 'circular', etc. o NULL
)
```

### Vista

`rag_indexing_status` — resumen de chunks/documentos por fuente y categoría.

---

## Fuentes cubiertas

### BCP — Banco Central del Paraguay

**Sitio:** `bcp.gov.py` (Liferay Portal + Cloudflare)

**Tecnología de scraping:** Playwright (Chromium headless) — el sitio requiere JS para renderizar el contenido.

**Sección indexada:**
- Normas Vigentes (`/web/institucional/vigentes`): ~697 documentos
  - Resoluciones de Directorio BCP
  - Resoluciones de Superintendencia de Bancos
  - Circulares SIB

**Categorías:**
- `resolucion` — Resoluciones del Directorio y SIB
- `circular` — Circulares SIB
- `reglamento` — Reglamentos
- `norma_prudencial` — Normas Prudenciales

**Nota importante:** Solo indexa normas **vigentes** (697 docs), no el historial completo. BCP no expone API pública; el scraper usa Playwright para renderizar el SPA.

---

### CONATEL — Comisión Nacional de Telecomunicaciones

**Sitio:** `conatel.gov.py` (WordPress, SSL inválido → `verify=False`)

**Tecnología de scraping:** `requests` + `BeautifulSoup4`

**Estructura de URLs:**
- Resoluciones: organizado por año (`/resoluciones-2025/`, `/resoluciones-2024/`, ...)
- Leyes, Decretos, Reglamentos: paginación flat (`/leyes/`, `/decretos/`, ...)

**Categorías:**
- `resolucion` — Resoluciones de Directorio (2011–2026, ~334 docs)
- `ley` — Leyes (~3 docs)
- `decreto` — Decretos (~3 docs)
- `reglamento` — Reglamentos (~1 doc)

**Total scraped:** ~341 documentos

---

## Estructura de archivos

```
aiquaa_rag/
├── .env.example          # Variables de entorno de ejemplo
├── re_embedder.py        # Agrega embeddings a chunks sin embedding
├── README.md             # Este archivo
│
├── BCP/
│   ├── .env              # Variables de entorno (Supabase + Voyage + Anthropic)
│   ├── scraper.py        # Scraper con Playwright (BCP usa Liferay + Cloudflare)
│   ├── indexer.py        # Pipeline: scraping → PDF → chunks → Supabase
│   └── query.py          # Consulta RAG con Claude
│
└── CONATEL/
    ├── .env              # Variables de entorno (mismo proyecto Supabase)
    ├── scraper.py        # Scraper con requests + BeautifulSoup4
    ├── indexer.py        # Pipeline: scraping → PDF → chunks → Supabase
    └── query.py          # Consulta RAG con Claude
```

---

## Variables de entorno

Copiar `.env.example` a `BCP/.env` y `CONATEL/.env`:

```env
SUPABASE_URL=https://hocryhxndegslzfiwlnx.supabase.co
SUPABASE_SERVICE_KEY=<service_role_key>
VOYAGE_API_KEY=<voyage_ai_key>       # solo para embeddings
ANTHROPIC_API_KEY=<anthropic_key>    # solo para query.py
```

---

## Instalación de dependencias

```bash
cd BCP   # o CONATEL
pip install pdfplumber requests beautifulsoup4 supabase python-dotenv
pip install pip-system-certs    # fix SSL en Windows
pip install playwright          # solo para BCP
python -m playwright install chromium  # descarga el browser

# Para embeddings:
pip install voyageai aiohttp tenacity aiolimiter

# Nota Python 3.14: usar supabase==2.9.1 (supabase>=2.10 requiere build tools C++)
pip install supabase==2.9.1
```

---

## Uso

### Indexar documentos (sin embeddings — no necesita Voyage AI)

```bash
# CONATEL — todas las categorías
cd CONATEL
python indexer.py --no-embed

# CONATEL — solo resoluciones
python indexer.py --no-embed --categories resolucion

# BCP — todas las normas vigentes
cd BCP
python indexer.py --no-embed

# BCP — solo circulares
python indexer.py --no-embed --categories circular

# Reindexar (borra chunks existentes y re-procesa)
python indexer.py --no-embed --reindex
```

### Generar embeddings (después de indexar)

```bash
cd ..   # root del proyecto
python re_embedder.py --dry-run        # ver cuántos chunks faltan embedding
python re_embedder.py --source conatel # embeddear solo CONATEL
python re_embedder.py --source bcp     # embeddear solo BCP
python re_embedder.py --batch-size 4   # lotes pequeños (free tier Voyage AI: 3 RPM)
```

### Consultar

```bash
# Requiere ANTHROPIC_API_KEY en .env

cd CONATEL
python query.py "¿Cuáles son los requisitos para obtener una licencia de ISP?"

cd BCP
python query.py "¿Qué normas regulan el encaje legal bancario?"

# Búsqueda unificada (BCP + CONATEL)
python query.py --source all "¿Qué regulaciones aplican a pagos electrónicos?"
```

---

## Flujo completo recomendado

```
1. Indexar sin embeddings (rápido, no necesita Voyage AI):
   cd CONATEL && python indexer.py --no-embed
   cd BCP     && python indexer.py --no-embed

2. Verificar qué quedó indexado:
   python re_embedder.py --dry-run

3. Agregar embeddings cuando tengas Voyage AI disponible:
   python re_embedder.py --source conatel --batch-size 4
   python re_embedder.py --source bcp     --batch-size 4

4. Consultar:
   cd CONATEL && python query.py "tu pregunta"
```

---

## Detalles técnicos

### Chunking
- Tamaño de chunk: **800 caracteres**
- Overlap: **150 caracteres**
- Estrategia: por párrafos; chunks grandes se dividen por palabras con overlap

### Embeddings
- Modelo: **`voyage-3`** (Voyage AI)
- Dimensiones: **1024**
- Índice vectorial: **HNSW** (cosine, m=16, ef_construction=64)
- Rate limit free tier Voyage AI: 3 RPM, 10K TPM

### PDF text extraction
- Librería: **pdfplumber** con `x_tolerance=2, y_tolerance=2`
- PDFs escaneados (solo imagen): se marcan como `error = "PDF sin texto extraíble"` y se omiten
- Muchos PDFs de CONATEL (especialmente 2023-2025) están escaneados

### SSL
- BCP: certificado válido, sin problemas
- CONATEL: certificado SSL inválido → `requests.get(..., verify=False)` + `warnings.filterwarnings`
- Windows SSL httpx/Supabase: resuelto con `pip install pip-system-certs`

### Anti-bot
- BCP: protección Cloudflare → requiere **Playwright** (Chromium headless)
- CONATEL: sin protección significativa, `requests` + User-Agent de browser suficiente

---

## Problemas conocidos

| Problema | Causa | Solución |
|----------|-------|----------|
| BCP: 403 Forbidden con `requests` | Cloudflare bloquea bots | Usar Playwright (ya implementado) |
| CONATEL PDFs sin texto | Documentos escaneados (imagen) | Implementar OCR (Tesseract/Azure) en el futuro |
| Voyage AI: rate limit | Free tier: 3 RPM | `--no-embed` + `re_embedder.py --batch-size 2` con delay |
| BCP: solo normas vigentes | El sitio no expone histórico en una sola página | Scrapear por año/filtro en el futuro |
| Python 3.14 + supabase>=2.10 | pyiceberg requiere C++ Build Tools | Usar `supabase==2.9.1` |

---

## Próximos pasos

- [ ] Agregar ANTHROPIC_API_KEY al `.env` para activar `query.py`
- [ ] Pagar plan Voyage AI o usar batch-size 2 con delay largo para embeddings
- [ ] Implementar OCR para PDFs escaneados (CONATEL 2023-2025)
- [ ] Ampliar BCP: scrapear historial por año/filtro desde la UI
- [ ] Agregar fuentes: SEPRELAD, SET, MIC, SENACSA, etc.
- [ ] Cron job para re-indexar periódicamente documentos nuevos
