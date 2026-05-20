import sqlite3
import argparse
import json

DB_PATH = "guatecompras_local.db"
PALABRAS_CLAVE_VIALES = [
    "carretera",
    "carreteras",
    "camino",
    "caminos",
    "vial",
    "puente",
    "paviment",
    "asfalt",
    "terracer",
    "adoquin",
    "adoquín",
    "balasto",
    "ruta",
]
ENTIDADES_OBJETIVO = [
    "unidad ejecutora de conservacion vial",
    "unidad ejecutora de conservación vial",
    "direccion general de caminos",
    "dirección general de caminos",
    "fondo social de solidaridad",
]
CATEGORIA_EJECUCION_OBRA = "works"


def normalizar_estado(estado):
    if not estado:
        return ""

    estado = estado.strip().lower()
    equivalencias = {
        "active": "vigente",
        "planned": "planificado",
        "cancelled": "cancelado",
        "complete": "completado",
        "unsuccessful": "no adjudicado",
        "withdrawn": "retirado",
    }
    return equivalencias.get(estado, estado)


def columna_existe(cursor, tabla, columna):
    cursor.execute(f"PRAGMA table_info({tabla})")
    return columna in [row[1] for row in cursor.fetchall()]


def consultar_concursos(
    limite=5,
    desde="2026-05-01",
    estado="vigente",
    solo_viales=False,
    solo_entidades_objetivo=True,
    solo_ejecucion_obra=True,
):
    conn = sqlite3.connect("guatecompras_local.db")
    cursor = conn.cursor()

    tiene_estado = columna_existe(cursor, "concursos", "estado")
    tiene_fecha_publicacion = columna_existe(cursor, "concursos", "fecha_publicacion")
    tiene_modalidad = columna_existe(cursor, "concursos", "modalidad")
    tiene_categoria = columna_existe(cursor, "concursos", "categoria")
    tiene_unidad_objetivo = columna_existe(cursor, "concursos", "unidad_objetivo")

    campos = ["nog", "entidad", "titulo", "fecha_cierre", "monto", "link"]
    if tiene_estado:
        campos.append("estado")
    if tiene_fecha_publicacion:
        campos.append("fecha_publicacion")
    if tiene_modalidad:
        campos.append("modalidad")
    if tiene_categoria:
        campos.append("categoria")
    if tiene_unidad_objetivo:
        campos.append("unidad_objetivo")

    filtros = []
    parametros = []

    if tiene_estado and estado:
        filtros.append("LOWER(COALESCE(estado, '')) = ?")
        parametros.append(normalizar_estado(estado))

    if tiene_fecha_publicacion and desde:
        filtros.append("date(substr(fecha_publicacion, 1, 10)) >= date(?)")
        parametros.append(desde)

    if solo_viales:
        texto_busqueda = "LOWER(COALESCE(titulo, '') || ' ' || COALESCE(descripcion, ''))"
        filtros.append("(" + " OR ".join([f"{texto_busqueda} LIKE ?" for _ in PALABRAS_CLAVE_VIALES]) + ")")
        parametros.extend([f"%{kw}%" for kw in PALABRAS_CLAVE_VIALES])

    if solo_entidades_objetivo:
        if tiene_unidad_objetivo:
            filtros.append("LOWER(COALESCE(unidad_objetivo, '')) IN (" + ", ".join(["?"] * len(ENTIDADES_OBJETIVO)) + ")")
            parametros.extend([entidad.lower() for entidad in ENTIDADES_OBJETIVO])
        else:
            texto_entidad = "LOWER(COALESCE(entidad, '') || ' ' || COALESCE(titulo, '') || ' ' || COALESCE(descripcion, ''))"
            filtros.append("(" + " OR ".join([f"{texto_entidad} LIKE ?" for _ in ENTIDADES_OBJETIVO]) + ")")
            parametros.extend([f"%{entidad.lower()}%" for entidad in ENTIDADES_OBJETIVO])

    if solo_ejecucion_obra and tiene_categoria:
        filtros.append("LOWER(COALESCE(categoria, '')) = ?")
        parametros.append(CATEGORIA_EJECUCION_OBRA)

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""

    cursor.execute(
        f"""
        SELECT {', '.join(campos)}
        FROM concursos
        {where_sql}
        ORDER BY monto DESC
        LIMIT ?
        """,
        (*parametros, limite),
    )
    
    resultados = cursor.fetchall()
    conn.close()
    
    # Estructuramos en JSON para que la IA lo procese sin errores
    lista_concursos = []
    for row in resultados:
        lista_concursos.append(dict(zip(campos, row)))
        
    print(json.dumps(lista_concursos, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lector de base de datos para Claudio")
    parser.add_argument("--limite", type=int, default=5, help="Cantidad de proyectos a traer")
    parser.add_argument("--desde", default="2026-05-01", help="Fecha mínima de publicación, formato YYYY-MM-DD")
    parser.add_argument("--estado", default="vigente", help="Estado a consultar, por defecto vigente")
    parser.add_argument("--solo-viales", action="store_true", help="Aplicar filtro adicional por palabras clave viales")
    parser.add_argument("--todos-los-sectores", action="store_true", help="Compatibilidad: no aplica filtro vial")
    parser.add_argument("--todas-las-entidades", action="store_true", help="No filtrar por entidades objetivo CIV")
    parser.add_argument("--incluir-servicios", action="store_true", help="No limitar a ejecución de obra")
    args = parser.parse_args()
    
    consultar_concursos(
        limite=args.limite,
        desde=args.desde,
        estado=args.estado,
        solo_viales=args.solo_viales and not args.todos_los_sectores,
        solo_entidades_objetivo=not args.todas_las_entidades,
        solo_ejecucion_obra=not args.incluir_servicios,
    )
