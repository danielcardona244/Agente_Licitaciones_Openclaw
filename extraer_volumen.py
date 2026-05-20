"""Extrae m² / ml / m³ de las bases de cada NOG vigente.

Pipeline por NOG:
  1. Consulta OCDS para obtener la lista de documentos.
  2. Descarga PDFs relevantes (bases, diseño, especificaciones) a pdfs_cache/.
  3. Extrae texto con pdfplumber.
  4. Invoca `openclaw capability model run --json` con prompt estructurado.
  5. Persiste m2_total / ml_total / m3_total / resumen_alcance / confianza en `concursos`.

Uso:
  .venv/bin/python extraer_volumen.py --nog 30098408         # procesa un NOG
  .venv/bin/python extraer_volumen.py --todos                # procesa todos los NOGs pendientes
  .venv/bin/python extraer_volumen.py --todos --reprocesar   # ignora cache de extracción
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

import pdfplumber

DB_PATH = "guatecompras_local.db"
CACHE_DIR = "pdfs_cache"
API_BASE = "https://ocds.guatecompras.gt"
MAX_TEXTO_PROMPT = 60000  # caracteres; deja margen frente a ARG_MAX y al contexto del modelo

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PALABRAS_DOCUMENTO_RELEVANTE = [
    "bases",
    "diseño",
    "diseno",
    "especificacion",
    "renglon",
    "cantidades",
    "presupuesto",
    "memoria",
]

PROMPT_SISTEMA = """Eres un ingeniero civil experto en bases de licitación pública de obra vial en Guatemala.
Te paso el texto extraído de los PDFs publicados en Guatecompras para un concurso.
Tu tarea: identificar cantidades físicas y datos críticos del proceso, devolver JSON ESTRICTO.

Estructura exacta (sin markdown, sin texto adicional):
{
  "m2_total": <número o null>,
  "ml_total": <número o null>,
  "m3_total": <número o null>,
  "resumen_alcance": "<una frase máx 200 chars>",
  "renglones_clave": [
    {"concepto": "<descripción corta>", "cantidad": <número>, "unidad": "m2|ml|m3|unidad"}
  ],
  "fechas": {
    "visita_tecnica": "<fecha y hora ISO o texto literal o null>",
    "lugar_visita": "<dirección o lugar de la visita técnica o null>",
    "recepcion_ofertas": "<fecha y hora o null>",
    "apertura_plicas": "<fecha y hora o null>",
    "consultas_aclaraciones": "<fecha límite o null>"
  },
  "plazos": {
    "plazo_ejecucion_dias": <número de días calendario o null>,
    "vigencia_oferta_dias": <número de días o null>,
    "tiempo_garantia_meses": <número de meses de garantía de obra o null>
  },
  "garantias_requeridas": [
    {"tipo": "sostenimiento|cumplimiento|anticipo|conservacion|otro",
     "porcentaje": <número o null>,
     "monto": <número o null>,
     "notas": "<texto opcional>"}
  ],
  "requisitos_oferente": ["<requisito 1>", "<requisito 2>"],
  "confianza": "alta|media|baja",
  "notas": "<si confianza no es alta, explica por qué>"
}

REGLAS:
- m2_total = suma de áreas de pavimento, carpeta asfáltica, adoquín, concreto, base granular, terracería superficial.
- ml_total = suma de metros lineales de camino, cuneta, bordillo, drenaje, señalización lineal.
- m3_total = suma de volúmenes de movimiento de tierra, excavación, base, subbase, relleno, concreto estructural.
- Para fechas: extrae lo que aparezca literal en las bases. Si la fecha viene en español ("15 de mayo de 2026") déjala así, no la traduzcas.
- Para visita técnica: muchas veces es obligatoria. Si las bases dicen "visita es obligatoria" agrégalo a notas.
- Plazos en días son calendario salvo que las bases especifiquen "hábiles".
- requisitos_oferente: hasta 8 requisitos clave para participar (RGAE activo, experiencia previa, capacidad financiera mínima, etc.). Resume cada uno en una frase.
- Si una sección no aparece, usa null o lista vacía (no inventes).
- Solo cantidades de obra física. NO incluyas honorarios, gastos administrativos, supervisión.
- Si el texto está cortado o ilegible: "confianza": "baja" y explica en "notas".
- Devuelve SOLO el JSON, nada más."""


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def buscar_release(nog):
    """Recupera el release de un NOG desde el OCDS."""
    # release/search no acepta NOG directo, paginamos hasta encontrarlo.
    # Para evitar paginar todo, intentamos primero un fetch directo por ocid.
    params = {"anio": "2026", "mes": "5", "Estatus_concurso": "1", "pagina": "1"}
    pagina = 1
    while pagina <= 50:
        params["pagina"] = str(pagina)
        url = f"{API_BASE}/release/search?" + urllib.parse.urlencode(params)
        data = http_json(url)
        for r in data.get("releases", []):
            if r.get("ocid", "").endswith(nog):
                return r
        if not data.get("links", {}).get("next"):
            break
        pagina += 1
    return None


def documentos_relevantes(release):
    docs = release.get("tender", {}).get("documents", []) or []
    relevantes = []
    for d in docs:
        url = d.get("url")
        titulo = (d.get("title") or "").lower()
        if not url or not url.lower().endswith(".pdf"):
            continue
        if any(palabra in titulo for palabra in PALABRAS_DOCUMENTO_RELEVANTE):
            relevantes.append({"titulo": d.get("title"), "url": url})
    # Si no detectamos por título, caemos al primero de tipo purchaseRequest o todos.
    if not relevantes:
        for d in docs:
            url = d.get("url")
            if url and url.lower().endswith(".pdf"):
                relevantes.append({"titulo": d.get("title"), "url": url})
    return relevantes


def descargar_pdf(url, destino):
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return destino
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp, open(destino, "wb") as f:
        f.write(resp.read())
    return destino


def pdf_a_texto(ruta):
    try:
        with pdfplumber.open(ruta) as pdf:
            partes = []
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if txt.strip():
                    partes.append(txt)
            return "\n\n".join(partes)
    except Exception as exc:
        return f"[ERROR_PDF: {exc}]"


def texto_consolidado(nog, documentos):
    bloques = []
    for doc in documentos:
        nombre = re.sub(r"[^a-zA-Z0-9_.-]+", "_", os.path.basename(urllib.parse.unquote(doc["url"])))[:120]
        ruta = os.path.join(CACHE_DIR, nog, nombre)
        try:
            descargar_pdf(doc["url"], ruta)
        except Exception as exc:
            bloques.append(f"### {doc['titulo']}\n[ERROR_DESCARGA: {exc}]")
            continue
        texto = pdf_a_texto(ruta)
        bloques.append(f"### {doc['titulo']}\n{texto}")
    return "\n\n".join(bloques)


def llamar_gpt(prompt_usuario):
    """Invoca el modelo configurado en OpenClaw y devuelve el dict JSON de salida."""
    prompt_completo = PROMPT_SISTEMA + "\n\n=== TEXTO DEL PDF ===\n" + prompt_usuario
    proc = subprocess.run(
        [
            "openclaw", "capability", "model", "run",
            "--prompt", prompt_completo,
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"openclaw error rc={proc.returncode}: {proc.stderr[:500]}")
    envoltorio = json.loads(proc.stdout)
    texto = envoltorio.get("outputs", [{}])[0].get("text", "")
    texto = texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)
    return json.loads(texto)


def asegurar_columnas(cursor):
    cursor.execute("PRAGMA table_info(concursos)")
    columnas = {row[1] for row in cursor.fetchall()}
    nuevas = {
        "m2_total": "ALTER TABLE concursos ADD COLUMN m2_total REAL",
        "ml_total": "ALTER TABLE concursos ADD COLUMN ml_total REAL",
        "m3_total": "ALTER TABLE concursos ADD COLUMN m3_total REAL",
        "resumen_alcance": "ALTER TABLE concursos ADD COLUMN resumen_alcance TEXT",
        "confianza_volumen": "ALTER TABLE concursos ADD COLUMN confianza_volumen TEXT",
        "renglones_json": "ALTER TABLE concursos ADD COLUMN renglones_json TEXT",
        "fecha_extraccion": "ALTER TABLE concursos ADD COLUMN fecha_extraccion TEXT",
        "notas_extraccion": "ALTER TABLE concursos ADD COLUMN notas_extraccion TEXT",
        "visita_tecnica": "ALTER TABLE concursos ADD COLUMN visita_tecnica TEXT",
        "lugar_visita": "ALTER TABLE concursos ADD COLUMN lugar_visita TEXT",
        "recepcion_ofertas": "ALTER TABLE concursos ADD COLUMN recepcion_ofertas TEXT",
        "apertura_plicas": "ALTER TABLE concursos ADD COLUMN apertura_plicas TEXT",
        "consultas_aclaraciones": "ALTER TABLE concursos ADD COLUMN consultas_aclaraciones TEXT",
        "plazo_ejecucion_dias": "ALTER TABLE concursos ADD COLUMN plazo_ejecucion_dias INTEGER",
        "vigencia_oferta_dias": "ALTER TABLE concursos ADD COLUMN vigencia_oferta_dias INTEGER",
        "tiempo_garantia_meses": "ALTER TABLE concursos ADD COLUMN tiempo_garantia_meses INTEGER",
        "garantias_json": "ALTER TABLE concursos ADD COLUMN garantias_json TEXT",
        "requisitos_oferente_json": "ALTER TABLE concursos ADD COLUMN requisitos_oferente_json TEXT",
    }
    for col, sql in nuevas.items():
        if col not in columnas:
            cursor.execute(sql)


def persistir(cursor, nog, datos):
    fechas = datos.get("fechas") or {}
    plazos = datos.get("plazos") or {}
    cursor.execute(
        """
        UPDATE concursos
           SET m2_total = ?,
               ml_total = ?,
               m3_total = ?,
               resumen_alcance = ?,
               confianza_volumen = ?,
               renglones_json = ?,
               notas_extraccion = ?,
               visita_tecnica = ?,
               lugar_visita = ?,
               recepcion_ofertas = ?,
               apertura_plicas = ?,
               consultas_aclaraciones = ?,
               plazo_ejecucion_dias = ?,
               vigencia_oferta_dias = ?,
               tiempo_garantia_meses = ?,
               garantias_json = ?,
               requisitos_oferente_json = ?,
               fecha_extraccion = ?
         WHERE nog = ?
        """,
        (
            datos.get("m2_total"),
            datos.get("ml_total"),
            datos.get("m3_total"),
            (datos.get("resumen_alcance") or "")[:300],
            datos.get("confianza"),
            json.dumps(datos.get("renglones_clave", []), ensure_ascii=False)[:4000],
            (datos.get("notas") or "")[:500],
            (fechas.get("visita_tecnica") or "")[:200] or None,
            (fechas.get("lugar_visita") or "")[:300] or None,
            (fechas.get("recepcion_ofertas") or "")[:200] or None,
            (fechas.get("apertura_plicas") or "")[:200] or None,
            (fechas.get("consultas_aclaraciones") or "")[:200] or None,
            plazos.get("plazo_ejecucion_dias"),
            plazos.get("vigencia_oferta_dias"),
            plazos.get("tiempo_garantia_meses"),
            json.dumps(datos.get("garantias_requeridas", []), ensure_ascii=False)[:2000],
            json.dumps(datos.get("requisitos_oferente", []), ensure_ascii=False)[:3000],
            datetime.utcnow().isoformat(timespec="seconds"),
            nog,
        ),
    )


def procesar_nog(cursor, nog, reprocesar=False):
    if not reprocesar:
        existente = cursor.execute(
            "SELECT fecha_extraccion FROM concursos WHERE nog = ?", (nog,)
        ).fetchone()
        if existente and existente[0]:
            print(f"  ⏭️  {nog}: ya extraído ({existente[0]})")
            return "saltado"

    print(f"  🔎 {nog}: buscando release en OCDS...")
    release = buscar_release(nog)
    if not release:
        print(f"  ❌ {nog}: no encontrado en OCDS")
        return "no_encontrado"

    docs = documentos_relevantes(release)
    if not docs:
        print(f"  ⚠️  {nog}: sin documentos PDF")
        return "sin_documentos"

    print(f"  📄 {nog}: {len(docs)} documento(s) — descargando y extrayendo texto...")
    texto = texto_consolidado(nog, docs)
    if len(texto) > MAX_TEXTO_PROMPT:
        texto = texto[:MAX_TEXTO_PROMPT] + "\n\n[...TEXTO TRUNCADO POR TAMAÑO...]"

    print(f"  🤖 {nog}: invocando GPT vía openclaw ({len(texto)} chars)...")
    try:
        datos = llamar_gpt(texto)
    except Exception as exc:
        print(f"  ❌ {nog}: error GPT — {exc}")
        return "error_gpt"

    persistir(cursor, nog, datos)
    print(
        f"  ✅ {nog}: m²={datos.get('m2_total')} ml={datos.get('ml_total')} "
        f"m³={datos.get('m3_total')} confianza={datos.get('confianza')}"
    )
    return "ok"


def listar_nogs_pendientes(cursor, reprocesar):
    if reprocesar:
        rows = cursor.execute("SELECT nog FROM concursos WHERE estado = 'vigente' ORDER BY nog").fetchall()
    else:
        rows = cursor.execute(
            "SELECT nog FROM concursos WHERE estado = 'vigente' AND (fecha_extraccion IS NULL OR fecha_extraccion = '') ORDER BY nog"
        ).fetchall()
    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Extractor de volumen físico vía OpenClaw+GPT")
    parser.add_argument("--nog", help="Procesa un NOG específico")
    parser.add_argument("--todos", action="store_true", help="Procesa todos los NOGs vigentes pendientes")
    parser.add_argument("--reprocesar", action="store_true", help="Ignora cache de fecha_extraccion")
    parser.add_argument("--limite", type=int, help="Procesa solo los primeros N NOGs (con --todos)")
    args = parser.parse_args()

    if not args.nog and not args.todos:
        parser.error("Debes pasar --nog NOG o --todos")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    asegurar_columnas(cursor)
    conn.commit()

    if args.nog:
        nogs = [args.nog]
    else:
        nogs = listar_nogs_pendientes(cursor, args.reprocesar)
        if args.limite:
            nogs = nogs[: args.limite]

    print(f"📋 NOGs a procesar: {len(nogs)}")
    contadores = {"ok": 0, "saltado": 0, "no_encontrado": 0, "sin_documentos": 0, "error_gpt": 0}

    for i, nog in enumerate(nogs, start=1):
        print(f"\n[{i}/{len(nogs)}] NOG {nog}")
        resultado = procesar_nog(cursor, nog, reprocesar=args.reprocesar)
        contadores[resultado] = contadores.get(resultado, 0) + 1
        conn.commit()

    conn.close()
    print(f"\n📊 Resumen: {contadores}")


if __name__ == "__main__":
    main()
