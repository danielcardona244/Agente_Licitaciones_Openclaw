import gzip
import argparse
import json
import sqlite3
import os
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

# Año de ejecución actual para el análisis de licitaciones
ANIO_ACTUAL = "2026"
API_BASE = "https://ocds.guatecompras.gt"
FECHA_DESDE = "2026-05-01"
ESTATUS_VIGENTE = "1"

# Raíz del workspace = el padre de la carpeta donde vive este script.
# Permite invocar el script desde cualquier cwd sin perder la DB ni el cache.
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE_DIR / "data"
DB_PATH = str(DATA_DIR / "guatecompras_local.db")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PALABRAS_CLAVE_VIALES = [
    "carretera", "carreteras",
    "camino", "caminos",
    "vial", "viales",
    "puente", "puentes",
    "paviment",
    "asfalt",
    "terracer",
    "adoquin", "adoquín",
    "balasto",
    "cuneta", "cunetas",
    "ruta",
    "calle", "calles",
]

ENTIDADES_OBJETIVO = [
    "unidad ejecutora de conservacion vial",
    "direccion general de caminos",
    "fondo social de solidaridad",
]

PREFIJOS_PRIORIDAD_MEDIA = [
    "municipalidad",
    "mancomunidad",
    "alcaldia",
    "alcaldía",
]

CATEGORIA_EJECUCION_OBRA = "works"
MODALIDAD_LICITACION_PUBLICA = "licitación pública"

COLUMNAS_EXTRACCION = [
    "m2_total",
    "ml_total",
    "m3_total",
    "resumen_alcance",
    "confianza_volumen",
    "renglones_json",
    "fecha_extraccion",
    "notas_extraccion",
    "visita_tecnica",
    "lugar_visita",
    "recepcion_ofertas",
    "apertura_plicas",
    "consultas_aclaraciones",
    "plazo_ejecucion_dias",
    "vigencia_oferta_dias",
    "tiempo_garantia_meses",
    "garantias_json",
    "requisitos_oferente_json",
]


def limpiar_texto(valor):
    valor = valor or ""
    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(char for char in valor if not unicodedata.combining(char))
    return valor.lower()


def texto_partes(record):
    partes = [
        record.get("buyer", {}).get("name", ""),
        record.get("tender", {}).get("title", ""),
        record.get("tender", {}).get("description", ""),
    ]
    for party in record.get("parties", []):
        partes.append(party.get("name", ""))
        partes.append(party.get("contactPoint", {}).get("name", ""))
        for member in party.get("memberOf", []):
            partes.append(member.get("name", ""))
    return limpiar_texto(" ".join(partes))


def unidad_objetivo_detectada(record):
    texto = texto_partes(record)
    for entidad in ENTIDADES_OBJETIVO:
        if entidad in texto:
            return entidad
    return None


def detectar_prioridad(record):
    """Devuelve ('alta'|'media'|'baja', unidad_objetivo_o_None)."""
    unidad = unidad_objetivo_detectada(record)
    if unidad:
        return "alta", unidad
    texto = texto_partes(record)
    if any(prefijo in texto for prefijo in PREFIJOS_PRIORIDAD_MEDIA):
        return "media", None
    return "baja", None


def es_obra_vial(record):
    tender = record.get("tender", {})
    texto = limpiar_texto(
        " ".join([tender.get("title", ""), tender.get("description", "")])
    )
    return any(palabra in texto for palabra in PALABRAS_CLAVE_VIALES)


def es_licitacion_publica(record):
    tender = record.get("tender", {})
    metodo = limpiar_texto(
        tender.get("procurementMethodDetails") or tender.get("procurementMethod") or ""
    )
    return "licitacion publica" in metodo


def normalizar_estado(estado):
    estado = limpiar_texto(estado).strip()
    equivalencias = {
        "active": "vigente",
        "planned": "planificado",
        "cancelled": "cancelado",
        "complete": "completado",
        "unsuccessful": "no adjudicado",
        "withdrawn": "retirado",
    }
    return equivalencias.get(estado, estado or "no especificado")


def extraer_fecha_publicacion(record, tender):
    candidatos = [
        tender.get("datePublished"),
        tender.get("tenderPeriod", {}).get("startDate"),
        tender.get("date"),
        record.get("publishedDate"),
        record.get("date"),
    ]
    return next((fecha for fecha in candidatos if fecha), "No especificada")


def obtener_json(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json,text/json,*/*",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" in content_type:
            raise ValueError(f"El endpoint devolvió HTML en lugar de JSON: {url}")
        return json.loads(response.read())


def iterar_releases_vigentes_desde_mayo():
    params = {
        "anio": ANIO_ACTUAL,
        "mes": "5",
        "Estatus_concurso": ESTATUS_VIGENTE,
        "ordenamiento": "Asc",
        "pagina": "1",
    }
    url = f"{API_BASE}/release/search?{urlencode(params)}"
    pagina = 1

    while url:
        try:
            data = obtener_json(url)
        except urllib.error.HTTPError as error:
            if error.code == 400 and pagina > 1:
                break
            raise
        releases = data.get("releases", [])
        if not releases:
            break

        for release in releases:
            tender = release.get("tender", {})
            fecha_publicacion = extraer_fecha_publicacion(release, tender)
            if fecha_publicacion[:10] >= FECHA_DESDE:
                yield release

        url = data.get("links", {}).get("next")
        pagina += 1
        if pagina > 500:
            raise RuntimeError("Se detuvo la paginación por seguridad después de 500 páginas.")


def preparar_schema(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS concursos (
            nog TEXT PRIMARY KEY,
            entidad TEXT,
            titulo TEXT,
            descripcion TEXT,
            fecha_publicacion TEXT,
            fecha_cierre TEXT,
            estado TEXT,
            modalidad TEXT,
            categoria TEXT,
            unidad_objetivo TEXT,
            prioridad TEXT,
            monto REAL,
            link TEXT
        )
    ''')

    cursor.execute("PRAGMA table_info(concursos)")
    columnas = {row[1] for row in cursor.fetchall()}
    migraciones = {
        "fecha_publicacion": "ALTER TABLE concursos ADD COLUMN fecha_publicacion TEXT",
        "estado": "ALTER TABLE concursos ADD COLUMN estado TEXT",
        "modalidad": "ALTER TABLE concursos ADD COLUMN modalidad TEXT",
        "categoria": "ALTER TABLE concursos ADD COLUMN categoria TEXT",
        "unidad_objetivo": "ALTER TABLE concursos ADD COLUMN unidad_objetivo TEXT",
        "prioridad": "ALTER TABLE concursos ADD COLUMN prioridad TEXT",
    }
    for columna, sql in migraciones.items():
        if columna not in columnas:
            cursor.execute(sql)


def columnas_tabla(cursor, tabla):
    cursor.execute(f"PRAGMA table_info({tabla})")
    return {row[1] for row in cursor.fetchall()}


def snapshot_extracciones(cursor):
    columnas = [c for c in COLUMNAS_EXTRACCION if c in columnas_tabla(cursor, "concursos")]
    if not columnas:
        return {}, []

    cursor.execute(f"SELECT nog, {', '.join(columnas)} FROM concursos")
    return {
        row[0]: dict(zip(columnas, row[1:]))
        for row in cursor.fetchall()
    }, columnas


def restaurar_extracciones(cursor, extracciones, columnas):
    if not extracciones or not columnas:
        return 0

    restauradas = 0
    asignaciones = ", ".join(f"{columna} = ?" for columna in columnas)
    for nog, datos in extracciones.items():
        valores = [datos.get(columna) for columna in columnas]
        cursor.execute(
            f"UPDATE concursos SET {asignaciones} WHERE nog = ?",
            (*valores, nog),
        )
        if cursor.rowcount:
            restauradas += 1
    return restauradas


def inicializar_sistema_datos():
    print(f"📥 Consultando API OCDS Guatecompras {ANIO_ACTUAL} desde {FECHA_DESDE}...")
    conn = None
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Crear tabla optimizada para nuestro Agente de Ofertas
        preparar_schema(cursor)
        extracciones_previas, columnas_extraccion = snapshot_extracciones(cursor)
        cursor.execute("DELETE FROM concursos")
        
        print("⚙️ Filtrando ejecución de obra vial en Licitación Pública vigente...")

        contador = 0
        por_prioridad = {"alta": 0, "media": 0, "baja": 0}
        for record in iterar_releases_vigentes_desde_mayo():
            tender = record.get("tender", {})
            categoria = tender.get("mainProcurementCategory", "")

            if categoria != CATEGORIA_EJECUCION_OBRA:
                continue
            if not es_licitacion_publica(record):
                continue
            if not es_obra_vial(record):
                continue

            nog = record.get("ocid", "").split("-")[-1]
            if not nog or nog == "Sin NOG":
                continue

            prioridad, unidad_objetivo = detectar_prioridad(record)
            entidad = record.get("buyer", {}).get("name", "Entidad no especificada")
            fecha_publicacion = extraer_fecha_publicacion(record, tender)
            fecha_cierre = tender.get("tenderPeriod", {}).get("endDate", "No especificada")
            estado = normalizar_estado(tender.get("statusDetails") or tender.get("status"))
            modalidad = tender.get("procurementMethodDetails") or tender.get("procurementMethod") or "No especificada"
            monto = tender.get("value", {}).get("amount", 0.0)
            link = f"https://www.guatecompras.gt/concursos/consultaConcur.aspx?nog={nog}"

            cursor.execute('''
                INSERT OR REPLACE INTO concursos (
                    nog, entidad, titulo, descripcion, fecha_publicacion,
                    fecha_cierre, estado, modalidad, categoria, unidad_objetivo,
                    prioridad, monto, link
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                nog,
                entidad,
                tender.get("title"),
                tender.get("description"),
                fecha_publicacion,
                fecha_cierre,
                estado,
                modalidad,
                categoria,
                unidad_objetivo,
                prioridad,
                monto,
                link,
            ))

            contador += 1
            por_prioridad[prioridad] = por_prioridad.get(prioridad, 0) + 1

        restauradas = restaurar_extracciones(
            cursor,
            extracciones_previas,
            columnas_extraccion,
        )
        conn.commit()
        print(
            f"✅ {contador} obras viales en Licitación Pública vigente indexadas desde {FECHA_DESDE}. "
            f"Alta: {por_prioridad['alta']} · Media: {por_prioridad['media']} · Baja: {por_prioridad['baja']}. "
            f"Extracciones preservadas: {restauradas}."
        )
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
            conn = None
        print(f"❌ Error al consultar la API OCDS: {e}")
        print("⚙️ Generando la DB de desarrollo con contingencia inmediata...")
        generar_db_desarrollo()
    finally:
        if conn:
            conn.close()

def generar_db_desarrollo():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    preparar_schema(cursor)
    
    # Datos de prueba con formato idéntico para que Claudio trabaje sin retrasos
    mock_data = [
        ("21460123", "CIV - Ministerio de Comunicaciones", "Construcción de Puente Vehicular Río Motagua", "Diseño y ejecución de puente de concreto pretensado sobre la ruta GUA-05.", "2026-05-08", "2026-07-02", "vigente", "Licitación Pública (Art. 17 LCE)", "works", "direccion general de caminos", "alta", 2800000.00, "https://www.guatecompras.gt/concursos/consultaConcur.aspx?nog=21460123")
    ]
    cursor.executemany('''
        INSERT OR REPLACE INTO concursos (
            nog, entidad, titulo, descripcion, fecha_publicacion,
            fecha_cierre, estado, modalidad, categoria, unidad_objetivo,
            prioridad, monto, link
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', mock_data)
    conn.commit()
    conn.close()
    print("✅ Base de datos local de desarrollo (`guatecompras_local.db`) creada con éxito con proyectos viales listos.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inicializa la base local con obras viales vigentes de Guatecompras OCDS."
    )
    parser.parse_args()
    inicializar_sistema_datos()
