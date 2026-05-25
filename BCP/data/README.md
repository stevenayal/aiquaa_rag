# BCP/data/

Datos exportados del sitio BCP para uso como seed o referencia.

## vigentes.json

**Fuente:** `https://www.bcp.gov.py/web/institucional/vigentes`  
**Fecha de extracción:** 2026-05-24  
**Total:** 697 documentos (normas vigentes)

Campos por documento:
- `url` — URL directa al PDF en el Liferay Document Library del BCP
- `title` — Título de la norma (ej: "Circular SB.SG. N° 56 de fecha 09.04.2026")
- `category` — `resolucion` | `circular` | `reglamento` | `norma_prudencial`
- `published` — Fecha ISO (extraída del título) o `null`
- `filename` — Nombre del archivo PDF

**Nota:** Las URLs no incluyen el parámetro `?t=` (timestamp de cache) para mantener
el archivo limpio y reproducible. Las URLs sin `?t=` funcionan igualmente para descarga.

**Uso en el indexer:**
Este archivo puede usarse como fallback si el scraper Playwright falla (Cloudflare).
El scraper principal (`scraper.py`) extrae esta data en tiempo real via Playwright.
