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

# Consultar la Ley de Contrataciones del Estado (Decreto 57-92)
.venv/bin/python tools/consultar_lce.py --articulo 65          # Artículo específico
.venv/bin/python tools/consultar_lce.py --buscar fianza        # Búsqueda por palabra clave
.venv/bin/python tools/consultar_lce.py --titulo V             # Filtrar por título romano
.venv/bin/python tools/consultar_lce.py --lista                # Listado completo (108 artículos)

# Extraer catálogo de renglones COVIAL desde una oferta histórica .xlsx
.venv/bin/python tools/extraer_catalogo.py \
    --origen ofertas_historicas/Oferta_SG-002-2026_OYL.xlsx

# Consultar Ley + Reglamento (--documento ley|reglamento|todos)
.venv/bin/python tools/consultar_lce.py --articulo 65 --documento reglamento
.venv/bin/python tools/consultar_lce.py --buscar fianza   # busca en ambos por default

# GENERAR OFERTA para un NOG (con datos del oferente como input runtime)
.venv/bin/python tools/generar_oferta.py \
    --nog 30098408 \
    --empresa "ORELLANA Y LEÓN CAPITAL, S.A." \
    --nit "1234567-8" \
    --representante "Rodrigo García Orellana" \
    --direccion "5ta calle 1-23 zona 10, Guatemala" \
    --telefono "5555-5555" \
    --correo "ofertas@oyl.gt" \
    --superintendente "Ing. Juan Pérez" \
    --colegiado "12345" \
    --tel-sup "5555-6666" \
    --tiempo-meses 7
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

## Ley de Contrataciones del Estado — Contexto de fondo

**Importante:** La LCE NO es una herramienta que Rodrigo consulta vía Telegram. Es el marco legal que Claudio aplica automáticamente al construir ofertas, checklists y análisis. Rodrigo no va a pedir "cítame el Art. 65" — espera que cuando Claudio diga "necesitas constituir fianza de cumplimiento", ese requisito ya tenga fundamento legal correcto.

- **Fuente versionada:** `referencias/lce/decreto-57-92.md` (108 artículos estructurados por título romano y capítulo, con reformas anotadas hasta 2015).
- **PDF oficial:** `referencias/lce/decreto-57-92.pdf` (publicación de la Contraloría General de Cuentas).
- **Ayudante interno del agente:** `tools/consultar_lce.py` permite a Claudio navegar artículos selectivamente sin cargar los 50KB del .md completo en su contexto. Útil para que el agente verifique un punto puntual durante su razonamiento (no para que el usuario lo invoque).

```bash
# Estos comandos los usa el AGENTE internamente, no son para Rodrigo en Telegram:
.venv/bin/python tools/consultar_lce.py --articulo 65          # Texto exacto de un artículo
.venv/bin/python tools/consultar_lce.py --buscar fianza        # Encontrar artículos relevantes
.venv/bin/python tools/consultar_lce.py --titulo V             # Todo un título romano
.venv/bin/python tools/consultar_lce.py --lista                # Índice completo
```

### Reglas LCE que deben aplicarse en TODO borrador de oferta o análisis legal

Estas son aplicación automática (no se le pide a Rodrigo confirmar cada una):

| Tema | Artículo | Regla |
|---|---|---|
| Modalidad | Art. 17, 38 | Licitación >Q900K · Cotización Q90K-Q900K · Compra directa Q10K-Q90K · Baja cuantía ≤Q10K |
| Precalificación | Art. 76 | Oferente debe estar inscrito en RGAE; sin inscripción = sin oferta |
| Declaración jurada | Art. 26 | Obligatoria: no estar comprendido en Art. 80 |
| Prohibiciones | Art. 80 | 14 causales; verificar TODAS antes de proponer (cónyuges, parientes, deudas SAT/IGSS, financiamiento político, etc.) |
| Fianza sostenimiento | Art. 64 | 1-5% del valor del contrato, vigencia 120 días |
| Fianza cumplimiento | Art. 65 | Según porcentaje del reglamento; cubre fallas durante ejecución |
| Fianza anticipo | Art. 66 | 100% del anticipo; reducible conforme se amortiza |
| Fianza conservación | Art. 67 | 15% del valor original; vigencia 18 meses post-recepción |
| Fianza saldos deudores | Art. 68 | 5% del valor original; simultánea con conservación |
| Anticipo en obras | Art. 58 | Hasta 20% del valor del contrato |
| Plazo de pago | Art. 62 | 30 días desde documentación completa |
| Multa por retraso | Art. 85 | 0.5/1000 por día, tope 5% del contrato |
| Ampliación de monto | Art. 52 | ≤20% órdenes de cambio; >20% y ≤40% contrato adicional |
| Pacto colusorio | Art. 25 Bis | Dos sociedades del mismo grupo en el mismo proceso = delito |

### Generación de oferta — Flujo y assets

**Cómo Rodrigo pedirá una oferta a Claudio (formato del mensaje):**

> *"Generá oferta para NOG 30098408. Empresa: ORELLANA Y LEÓN CAPITAL, S.A. · NIT: 1234567-8 · Representante legal: Rodrigo García Orellana · Dirección: [...] · Teléfono: [...] · Correo: [...] · Superintendente: Ing. Juan Pérez · Colegiado: 12345 · Tel sup: 5555-5555"*

Claudio NO almacena los datos del oferente entre ofertas — pueden cambiar (no siempre se oferta con la misma empresa). Cada oferta es independiente.

**🚨 REGLA CATEGÓRICA:** Claudio NUNCA debe generar el .xlsx por su cuenta (ni con openpyxl directo, ni con pandas, ni con ninguna otra herramienta). El ÚNICO camino válido es invocar `tools/generar_oferta.py`. El script ya tiene el formato OYL correcto (13+ hojas con colores corporativos), aplica las reglas LCE, y guarda en una ruta permitida por OpenClaw para adjuntar en Telegram. Improvisar un .xlsx propio rompe el formato Y bloquea el envío de Telegram (LocalMediaAccessError).

**Lo que Claudio debe hacer cuando reciba ese mensaje:**

1. Ejecutar directamente `tools/generar_oferta.py` con los args del mensaje:
   ```bash
   .venv/bin/python tools/generar_oferta.py \
       --nog NNNN --empresa "..." --nit "..." \
       --representante "..." --direccion "..." \
       --telefono "..." --correo "..." \
       --superintendente "..." --colegiado "..." \
       --tel-sup "..." --tiempo-meses N
   ```
   El script ya hace todo el trabajo internamente: lee el NOG de la DB, carga el catálogo, calcula precios, aplica las reglas LCE y genera el .xlsx con formato OYL.

2. La salida estándar del script reporta la ruta absoluta del archivo generado y un resumen (renglones con precio, faltantes). Capturar esa ruta.

3. **ADJUNTAR el archivo .xlsx en la respuesta de Telegram** usando la capacidad nativa de envío de archivos del canal. La ruta absoluta del archivo es `/Users/rodrigo/.openclaw/workspace/data/ofertas_generadas/Oferta_{NOG}_{empresa}_{fecha}.xlsx`. NO solo pegar el path como texto — debe ir como **adjunto/documento** en el mensaje de Telegram para que Rodrigo lo abra con un toque.

4. Acompañar el adjunto con un mensaje corto en Telegram: NOG, total ofertado, renglones matcheados vs. pendientes, y datos del oferente que quedaron como `[FALTA: ...]` para que Rodrigo los complete antes de presentar.

**Assets disponibles:**
- ✅ Ley de Contrataciones del Estado → contexto legal de fondo (`referencias/lce/decreto-57-92.md`)
- ✅ Reglamento de la LCE (Acuerdo Gubernativo 122-2016, 83 artículos) → `referencias/lce/reglamento.md`
- ✅ Plantilla de oferta histórica → estructura documentada en `docs/FORMATO_OFERTA.md`
- ✅ **Catálogo unificado de renglones** (`data/catalogo_renglones.json`) — 56 renglones (33 de señalización derivados de oferta OYL + 23 de obra vial general: terracería, base, pavimento rígido, adoquín, drenajes, estructuras, mitigación).
- ✅ **Generador de oferta** → `tools/generar_oferta.py` (genera .xlsx con formato OYL, marca faltantes)

### Catálogo de precios — política operativa

El generador busca en este orden:
1. `referencias/catalogo_renglones_covial.json` — catálogo oficial del cliente (cuando exista, gana sobre el local).
2. `data/catalogo_renglones.json` — catálogo unificado del workspace (default actual).

Cuando llegue el catálogo oficial del cliente:
- Se guarda en `referencias/catalogo_renglones_covial.json`.
- El generador automáticamente lo prioriza sobre el local.
- En ese momento el `data/catalogo_renglones.json` local puede borrarse o dejarse de fallback.

**Pendientes:**
- ⏳ Catálogo oficial completo del cliente → cuando llegue, lo ubicas en `referencias/catalogo_renglones_covial.json` y `generar_oferta.py` lo usa automáticamente (tiene prioridad sobre el derivado).
- ⏳ Más ofertas históricas (pavimento rígido, terracería, drenaje, estructuras) → corro `extraer_catalogo.py` sobre cada una y voy ampliando cobertura del catálogo derivado mientras llega el oficial.
- ⏳ Refinar el extractor (`extraer_volumen.py`) para detectar códigos COVIAL en los renglones del PDF si están presentes. Actualmente devuelve solo descripción, por eso el match catálogo↔NOG falla en casi todos los casos. Cuando llegue el catálogo oficial con sus códigos, ajustar el prompt para que extraiga el código junto con la descripción.

Vamos a construir `generar_oferta.py --nog NNNN` que combine las bases del NOG con esos contextos para producir un borrador estructurado. Hasta entonces, el flujo cierra en la ficha detalle.

## Rutina Diaria: Carreteras por Unidad Compradora
- **Criterios persistentes:** ver `GUATECOMPRAS_CRITERIOS.md`.
- **Unidades objetivo diarias:**
  - Unidad Ejecutora de Conservación Vial
  - Compras DGC
  - Fondo Social de Solidaridad
- **Ranking solicitado:** conveniencia ordenada por volumen de obra, de mayor a menor.
- **Nota técnica:** si OCDS no trae cantidades físicas, revisar o señalar la necesidad de descargar bases/anexos para extraer m², ml, m³ y renglones de obra.
