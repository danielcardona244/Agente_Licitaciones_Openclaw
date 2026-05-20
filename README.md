# Claudio — Agente para Licitaciones Guatecompras

Agente de IA construido sobre [OpenClaw](https://docs.openclaw.ai) que descubre, analiza y (próximamente) prepara ofertas para licitaciones públicas de obra vial en Guatemala. Opera vía Telegram (`@LicitadorClaudioBot`) y conversa con GPT-5.5 vía la sesión autenticada de OpenClaw.

---

## Pipeline en tres pasos

1. **Ingest OCDS** — [`tools/inicializar_db.py`](tools/inicializar_db.py) baja releases de `https://ocds.guatecompras.gt/release/search`, filtra `mainProcurementCategory=works` + Licitación Pública + palabras viales (carretera, camino, pavimento, etc.) y los etiqueta con prioridad:
   - **alta** → UECV, Dirección General de Caminos, Fondo Social de Solidaridad
   - **media** → municipalidades, mancomunidades, alcaldías
   - **baja** → otras entidades

2. **Extracción de bases** — [`tools/extraer_volumen.py`](tools/extraer_volumen.py) descarga los PDFs publicados de cada NOG (bases, diseño, especificaciones), saca texto con pdfplumber y los pasa a GPT-5.5 vía `openclaw capability model run`. Devuelve JSON estructurado con m²/ml/m³, fechas (visita técnica, plicas), plazos, garantías requeridas, requisitos para participar y renglones de obra.

3. **Consulta** — [`tools/consultar_db.py`](tools/consultar_db.py) produce reportes Markdown listos para Telegram:
   - **Listado:** `--limite N` → top N por m² DESC, solo m² visible
   - **Ficha detalle:** `--nog NNNN` → alcance + fechas + plazos + garantías + requisitos + renglones

---

## Estructura del workspace

```
workspace/
├── AGENTS.md, SOUL.md, USER.md, IDENTITY.md   ← contexto del agente (raíz)
├── HEARTBEAT.md, TOOLS.md, MEMORY.md          ← contexto OpenClaw (raíz)
├── memory/YYYY-MM-DD.md                       ← notas diarias del agente
├── tools/                                     ← scripts Python (3)
├── bin/                                       ← arrancar/apagar Claudio (shell)
├── data/                                      ← DB + pdfs_cache + log (ignorado en git)
├── docs/                                      ← criterios operativos, doc del dominio
├── referencias/                               ← FUTURO: LCE + decretos
├── ofertas_historicas/                        ← FUTURO: ofertas previas (ignorado en git)
└── .venv/                                     ← entorno Python (ignorado en git)
```

Los scripts Python resuelven sus paths con `Path(__file__).resolve().parent.parent`, así que la DB y el cache de PDFs siempre se encuentran en `data/` independiente del directorio desde el que se invoquen.

---

## Setup en máquina nueva

```bash
# 1. Clonar el repo (donde corresponda)
git clone <url>
cd <repo>

# 2. Crear el venv y dependencias
python3 -m venv .venv
.venv/bin/pip install requests pdfplumber pdfminer.six

# 3. Asegurarse de tener OpenClaw instalado y autenticado vía onboard
openclaw capability model auth status   # debe mostrar provider 'openai-codex' usable

# 4. Generar la DB inicial desde Guatecompras
.venv/bin/python tools/inicializar_db.py

# 5. (Opcional) Extraer bases de los NOGs vigentes
.venv/bin/python tools/extraer_volumen.py --todos
```

---

## Operación diaria

### Encender / apagar Claudio

Hay dos apps en el Escritorio (creadas con Automator) que invocan los scripts en `bin/`:

- **Despertar a Claudio** → controla el LaunchAgent `ai.openclaw.gateway` vía `launchctl bootstrap/kickstart`.
- **Apagar a Claudio** → descarga el LaunchAgent con `launchctl bootout` y verifica que el puerto 18789 quede libre.

También se pueden invocar directamente:
```bash
bin/arrancar_claudio.sh
bin/apagar_claudio.sh
```

### Comandos clave

```bash
# Refrescar DB con releases vigentes (preserva extracciones ya hechas)
.venv/bin/python tools/inicializar_db.py

# Extraer bases de un NOG específico
.venv/bin/python tools/extraer_volumen.py --nog 30098408

# Extraer en tandas de 10 para no saturar la sesión
.venv/bin/python tools/extraer_volumen.py --todos --limite 10

# Reporte ejecutivo: top 5 ranking por m²
.venv/bin/python tools/consultar_db.py --limite 5

# Ficha completa de un NOG (fechas, plazos, garantías, renglones)
.venv/bin/python tools/consultar_db.py --nog 30098408
```

---

## Cómo hacer commits

El `.gitignore` ya excluye lo regenerable (DB, pdfs_cache, logs) y lo sensible (datos del oferente, ofertas históricas, .env). Antes de cada commit:

```bash
git status            # revisa que NADA de data/ ni .venv/ aparezca
git add -A
git commit -m "..."
```

**Reglas que el .gitignore protege:**

| Categoría | Patrón | Razón |
|---|---|---|
| Datos regenerables | `data/guatecompras_local.db`, `data/pdfs_cache/`, `data/*.log` | Se reconstruyen desde OCDS |
| Sensible del oferente | `OFERENTE.md`, `ofertas_historicas/*`, `.env`, `*.pem`, `*.key` | Datos comerciales/fiscales/legales |
| Estado OpenClaw | `.openclaw/` | Estado runtime del framework |
| Entorno Python | `.venv/`, `__pycache__/`, `*.pyc` | Dependencias locales |
| Sistema | `.DS_Store`, `._*`, IDE caches | Ruido del sistema operativo |

**Commit de la reorganización a carpetas** (si todavía está pendiente):

```bash
git add -A
git commit -m "Reorganización por carpetas: tools/, bin/, data/, docs/

- Scripts Python movidos a tools/ con paths resueltos desde __file__
- Scripts shell movidos a bin/, apps Automator actualizadas
- DB y pdfs_cache movidos a data/ (ahora en .gitignore)
- GUATECOMPRAS_CRITERIOS.md movido a docs/
- Carpetas referencias/ y ofertas_historicas/ listas para LCE y ofertas previas
- .gitignore comprehensivo: datos regenerables, sensibles, sistema, IDE"
```

---

## Estado actual

| Componente | Estado |
|---|---|
| Gateway OpenClaw | LaunchAgent `ai.openclaw.gateway` en puerto 18789 (gestionado por launchd) |
| DB local | 42 concursos vigentes desde 2026-05-01 |
| Extracciones completas | 5 NOGs (37 pendientes) |
| Modelo de extracción | `openai/gpt-5.5` vía OpenClaw onboard |

---

## Roadmap

- [ ] Procesar los 37 NOGs pendientes con `extraer_volumen.py --todos`
- [ ] Cargar Ley de Contrataciones del Estado + decretos a `referencias/`
- [ ] Cargar ofertas históricas exitosas a `ofertas_historicas/` (local, no se sube)
- [ ] Crear `OFERENTE.md` con datos del licitador (local, no se sube)
- [ ] Construir `tools/generar_oferta.py --nog NNNN` para borradores automatizados
