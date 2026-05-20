# TOOLS.md - Herramientas de Datos Local

## Estructura del workspace

```
workspace/
├── AGENTS.md, SOUL.md, USER.md, IDENTITY.md   ← contexto OpenClaw (raíz)
├── HEARTBEAT.md, TOOLS.md (este), MEMORY.md   ← contexto OpenClaw (raíz)
├── memory/YYYY-MM-DD.md                       ← memoria diaria
├── tools/                                     ← scripts Python (inicializar/extraer/consultar)
├── bin/                                       ← arrancar_claudio.sh, apagar_claudio.sh
├── data/                                      ← DB, pdfs_cache, logs
├── docs/                                      ← GUATECOMPRAS_CRITERIOS.md y otra doc del dominio
├── referencias/                               ← FUTURO: LCE, decretos
├── ofertas_historicas/                        ← FUTURO: ofertas previas exitosas
└── .venv/                                     ← entorno Python
```

Los scripts Python resuelven sus paths con `Path(__file__).resolve().parent.parent`, por lo que la DB y el pdfs_cache siempre se encuentran en `data/` sin importar desde dónde se invoquen.

## Entorno Python

Usar siempre el venv del workspace: `.venv/bin/python` (Python 3.9.6 con `requests`, `pdfplumber`, `pdfminer.six`). No invocar `python` ni `python3` global de Homebrew para no perder dependencias.

## Pipeline en tres pasos

1. **Ingest OCDS (`inicializar_db.py`)** baja `https://ocds.guatecompras.gt/release/search` (`Estatus_concurso=1`) y guarda **solo obras viales en Licitación Pública vigente**, sin importar la entidad. Al refrescar, preserva las extracciones ya guardadas (`m2_total`, fechas, garantías, requisitos, renglones) para los NOGs que siguen vigentes. Filtros aplicados en ingest:
   - `mainProcurementCategory = works`
   - Modalidad contiene "Licitación Pública"
   - Título o descripción contiene palabras viales (carretera, camino, vial, puente, pavimento, asfalto, terracería, adoquín, balasto, cuneta, ruta, calle)
   - Cada registro se etiqueta con `prioridad`:
     - **alta** → Unidad Ejecutora de Conservación Vial, Dirección General de Caminos, Fondo Social de Solidaridad
     - **media** → municipalidades, mancomunidades o alcaldías
     - **baja** → cualquier otra entidad

2. **Extracción de bases (`extraer_volumen.py`)** baja los PDFs publicados de cada NOG (bases, diseño, especificaciones), saca texto con pdfplumber, y los manda a `openclaw capability model run --json` (modelo `openai/gpt-5.5` autenticado vía OpenClaw onboard, sin API key separada). El modelo devuelve JSON estructurado con:
   - Volumen: `m2_total`, `ml_total`, `m3_total`, `resumen_alcance`, `renglones_clave`
   - Fechas: visita técnica, lugar de visita, recepción de ofertas, apertura de plicas, consultas/aclaraciones
   - Plazos: ejecución (días calendario), vigencia oferta, garantía de obra
   - `garantias_requeridas` (tipo, %, monto, notas)
   - `requisitos_oferente` (hasta 8 requisitos clave para participar)
   - `confianza` (alta|media|baja) y `notas`

   PDFs se cachean en `pdfs_cache/{NOG}/`. La extracción es idempotente — los NOGs con `fecha_extraccion` set ya no se reprocesan salvo `--reprocesar`.

3. **Consulta (`consultar_db.py`)** produce dos vistas:
   - **Listado:** ranking por `m2_total DESC`. Solo muestra m² (ignora ml/m³ por decisión operativa). NOGs sin extracción aparecen al final como _m² pendiente_.
   - **Ficha detalle (`--nog NOG`):** todo lo que tenga el NOG — alcance, volúmenes completos, fechas críticas, plazos, garantías, requisitos, renglones, link.

## Comandos clave

```bash
# Refrescar la DB con releases vigentes de Guatecompras
.venv/bin/python tools/inicializar_db.py

# Extraer volumen físico de UN NOG (POC)
.venv/bin/python tools/extraer_volumen.py --nog 30098408

# Extraer volumen físico de TODOS los pendientes (~30s por NOG)
.venv/bin/python tools/extraer_volumen.py --todos

# Limitar la corrida masiva (útil para no procesarlos todos de golpe)
.venv/bin/python tools/extraer_volumen.py --todos --limite 10

# Reprocesar incluso si ya estaba extraído
.venv/bin/python tools/extraer_volumen.py --todos --reprocesar

# Reporte ejecutivo top 5 ranking por m²
.venv/bin/python tools/consultar_db.py --limite 5

# Ficha completa de un NOG específico (fechas visita técnica, plicas, plazos, garantías, requisitos, renglones)
.venv/bin/python tools/consultar_db.py --nog 30098408
```

## Herramienta Core: Consultar Obras Viales

- **Comando por defecto:** `.venv/bin/python tools/consultar_db.py` → top 5 vigente desde 2026-05-01, prioridad `alta,media`, ranking por m² DESC, salida formateada.
- **Argumentos:**
  - `--limite X` (default 5)
  - `--desde YYYY-MM-DD` (default `2026-05-01`)
  - `--estado ESTADO` (default `vigente`)
  - `--prioridad alta|media|baja|todas|csv` (default `alta,media`). Ejemplo: `--prioridad alta` para enfocarse solo en UECV/DGC/FSS.
  - `--json` para imprimir JSON crudo en vez del reporte formateado.

### Instrucciones de Despliegue para Claudio
Cuando Rodrigo solicite reportes, top de montos o listados de licitaciones:
1. **Listado:** ejecuta `.venv/bin/python tools/consultar_db.py --limite 5`. La salida es Markdown Telegram-ready, ranking por m² DESC, solo muestra m² (no ml ni m³).
2. **Rodrigo elige un NOG de interés:** ejecuta `.venv/bin/python tools/consultar_db.py --nog NNNN` y devuélvele la ficha completa: alcance, volúmenes totales, fechas de visita técnica, recepción de plicas, plazos, garantías, requisitos para participar y renglones.
3. Si Rodrigo pide enfocarse solo en sus entidades objetivo, agrega `--prioridad alta`.
4. Si la ficha indica que el NOG aún no tiene extracción, ofrécele correr `extraer_volumen.py --nog NNNN` y volver a consultar.
5. Si las fechas vienen con placeholders tipo `XX DE XXXXX DEL 2,026 XX:XX`, eso es real — la municipalidad aún no fijó fecha. Sugiérele a Rodrigo llamar a la entidad para confirmar.
6. El campo `monto` viene Q0.00 en casi todos los releases — Guatecompras no publica `tender.value.amount`. El ranking por m² reemplaza al monto como criterio de conveniencia.

### Futuro frente: Generación de oferta (pendiente)
Cuando Rodrigo entregue PDFs de:
- Ley de Contrataciones del Estado + reglamento + decretos relevantes → `referencias/lce/`
- Ofertas históricas exitosas → `ofertas_historicas/`
- Datos del oferente (NIT, razón social, RGAE, capacidades) → `OFERENTE.md` (fuera de git si es sensible)

Vamos a construir `generar_oferta.py --nog NNNN` que combine las bases del NOG con esos contextos para producir un borrador estructurado. Hasta entonces, el flujo cierra en la ficha detalle.

## Rutina Diaria: Carreteras por Unidad Compradora
- **Criterios persistentes:** ver `GUATECOMPRAS_CRITERIOS.md`.
- **Unidades objetivo diarias:**
  - Unidad Ejecutora de Conservación Vial
  - Compras DGC
  - Fondo Social de Solidaridad
- **Ranking solicitado:** conveniencia ordenada por volumen de obra, de mayor a menor.
- **Nota técnica:** si OCDS no trae cantidades físicas, revisar o señalar la necesidad de descargar bases/anexos para extraer m², ml, m³ y renglones de obra.
