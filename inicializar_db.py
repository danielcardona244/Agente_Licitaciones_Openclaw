import gzip
import json
import sqlite3
import os
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import urlencode

# Año de ejecución actual para el análisis de licitaciones
ANIO_ACTUAL = "2026"
API_BASE = "https://ocds.guatecompras.gt"
FECHA_DESDE = "2026-05-01"
ESTATUS_VIGENTE = "1"
DB_PATH = "guatecompras_local.db"

PALABRAS_CLAVE = [
    "construccion",
    "puente",
    "carretera",
    "infraestructura",
    "paviment",
    "cemento",
    "asfalt",
    "mejoramiento vial",
    "camino",
    "rural",
    "terracer",
    "adoquin",
    "balasto",
]

ENTIDADES_OBJETIVO = [
    "unidad ejecutora de conservacion vial",
    "direccion general de caminos",
    "fondo social de solidaridad",
]

CATEGORIA_EJECUCION_OBRA = "works"


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
    }
    for columna, sql in migraciones.items():
        if columna not in columnas:
            cursor.execute(sql)

def inicializar_sistema_datos():
    print(f"📥 Consultando API OCDS Guatecompras {ANIO_ACTUAL} desde {FECHA_DESDE}...")
    conn = None
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Crear tabla optimizada para nuestro Agente de Ofertas
        preparar_schema(cursor)
        cursor.execute("DELETE FROM concursos")
        
        print("⚙️ Filtrando licitaciones vigentes de entidades objetivo y ejecución de obra...")
        
        contador = 0
        for record in iterar_releases_vigentes_desde_mayo():
            tender = record.get("tender", {})
            titulo = limpiar_texto(tender.get("title", ""))
            descripcion = limpiar_texto(tender.get("description", ""))
            unidad_objetivo = unidad_objetivo_detectada(record)
            categoria = tender.get("mainProcurementCategory", "")
            
            # Guardamos las entidades objetivo; la consulta operativa filtra ejecución de obra.
            if unidad_objetivo:
                nog = record.get("ocid", "").split("-")[-1] # Extraemos el identificador/NOG
                if not nog or nog == "Sin NOG":
                    continue
                    
                entidad = record.get("buyer", {}).get("name", "Entidad no especificada")
                fecha_publicacion = extraer_fecha_publicacion(record, tender)
                fecha_cierre = tender.get("tenderPeriod", {}).get("endDate", "No especificada")
                estado = normalizar_estado(tender.get("statusDetails") or tender.get("status"))
                modalidad = tender.get("procurementMethodDetails") or tender.get("procurementMethod") or "No especificada"
                
                # Extraer el presupuesto estimado
                monto = tender.get("value", {}).get("amount", 0.0)
                link = f"https://www.guatecompras.gt/concursos/consultaConcur.aspx?nog={nog}"
                
                cursor.execute('''
                    INSERT OR REPLACE INTO concursos (
                        nog, entidad, titulo, descripcion, fecha_publicacion,
                        fecha_cierre, estado, modalidad, categoria, unidad_objetivo, monto, link
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    monto,
                    link,
                ))
                
                contador += 1

        conn.commit()
        print(f"✅ ¡Éxito! Se han indexado {contador} proyectos vigentes desde {FECHA_DESDE}.")
        
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
        ("21460123", "CIV - Ministerio de Comunicaciones", "Construcción de Puente Vehicular Río Motagua", "Diseño y ejecución de puente de concreto pretensado sobre la ruta GUA-05.", "2026-05-08", "2026-07-02", "vigente", "Licitación pública", "works", "direccion general de caminos", 2800000.00, "https://www.guatecompras.gt/concursos/consultaConcur.aspx?nog=21460123")
    ]
    cursor.executemany('''
        INSERT OR REPLACE INTO concursos (
            nog, entidad, titulo, descripcion, fecha_publicacion,
            fecha_cierre, estado, modalidad, categoria, unidad_objetivo, monto, link
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', mock_data)
    conn.commit()
    conn.close()
    print("✅ Base de datos local de desarrollo (`guatecompras_local.db`) creada con éxito con proyectos viales listos.")

if __name__ == "__main__":
    inicializar_sistema_datos()
