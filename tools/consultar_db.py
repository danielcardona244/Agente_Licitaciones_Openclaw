import sqlite3
import argparse
import json
from datetime import datetime
from pathlib import Path

# Raíz del workspace = el padre de la carpeta donde vive este script.
# Permite invocar el script desde cualquier cwd sin perder la DB.
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = str(WORKSPACE_DIR / "data" / "guatecompras_local.db")

EQUIVALENCIAS_ESTADO = {
    "active": "vigente",
    "planned": "planificado",
    "cancelled": "cancelado",
    "complete": "completado",
    "unsuccessful": "no adjudicado",
    "withdrawn": "retirado",
}

BADGES_PRIORIDAD = {
    "alta": "🟢 ALTA",
    "media": "🟡 MEDIA",
    "baja": "⚪ BAJA",
}


def normalizar_estado(estado):
    if not estado:
        return ""
    estado = estado.strip().lower()
    return EQUIVALENCIAS_ESTADO.get(estado, estado)


def columna_existe(cursor, tabla, columna):
    cursor.execute(f"PRAGMA table_info({tabla})")
    return columna in [row[1] for row in cursor.fetchall()]


def formatear_monto(valor):
    try:
        return f"Q{float(valor):,.2f}"
    except (TypeError, ValueError):
        return "Q0.00"


def formatear_fecha(valor):
    if not valor or valor == "No especificada":
        return "no especificada"
    return str(valor)[:10]


def titulo_unidad(valor):
    if not valor:
        return None
    palabras = valor.split()
    pequenas = {"de", "del", "la", "las", "el", "los", "y"}
    return " ".join(
        palabra if palabra in pequenas else palabra.capitalize()
        for palabra in palabras
    )


def formatear_volumen(valor, unidad):
    if valor is None:
        return None
    try:
        return f"{float(valor):,.1f} {unidad}"
    except (TypeError, ValueError):
        return None


def construir_reporte(concursos, desde, prioridades):
    badges_pedidos = ", ".join(BADGES_PRIORIDAD.get(p, p.upper()) for p in prioridades)
    encabezado = [
        "🛣️ *Reporte Guatecompras — Obras viales en Licitación Pública vigente*",
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} · Desde: {desde}",
        f"Prioridades: {badges_pedidos}",
    ]

    if not concursos:
        encabezado.append("")
        encabezado.append("⚠️ Sin resultados que cumplan los criterios operativos.")
        return "\n".join(encabezado)

    con_volumen = sum(1 for c in concursos if c.get("m2_total"))
    encabezado.append(
        f"Total: {len(concursos)} proyecto(s) · ranking por m² · "
        f"{con_volumen}/{len(concursos)} con volumen extraído"
    )

    bloques = []
    for idx, c in enumerate(concursos, start=1):
        badge = BADGES_PRIORIDAD.get(c.get("prioridad"), "")
        m2 = formatear_volumen(c.get("m2_total"), "m²")
        cabecera = f"*{idx}. NOG {c.get('nog', 'N/A')}*"
        if m2:
            cabecera += f"  —  *{m2}*"
        else:
            cabecera += "  —  _m² pendiente_"
        if badge:
            cabecera += f"  ·  {badge}"
        lineas = [
            cabecera,
            f"Proyecto: {c.get('titulo') or 'Sin título'}",
            f"Entidad: {c.get('entidad') or 'No especificada'}",
        ]
        resumen = c.get("resumen_alcance")
        if resumen:
            lineas.append(f"Alcance: {resumen}")
        confianza = c.get("confianza_volumen")
        if confianza and confianza != "alta":
            lineas.append(f"⚠️ Confianza extracción: {confianza}")
        lineas.append(
            f"Publicación: {formatear_fecha(c.get('fecha_publicacion'))}  ·  "
            f"Cierre: {formatear_fecha(c.get('fecha_cierre'))}"
        )
        link = c.get("link")
        if link:
            lineas.append(f"🔗 {link}")
        bloques.append("\n".join(lineas))

    pie = (
        "—\n"
        "Ranking por m² total. Para ficha completa (fechas de visita técnica, apertura de plicas, plazo de ejecución, renglones) "
        "pedir `consultar_db.py --nog NOG`."
    )

    return "\n".join(encabezado) + "\n\n" + "\n\n".join(bloques) + "\n\n" + pie


def construir_ficha(c):
    if not c:
        return "⚠️ NOG no encontrado en la base de datos local. Corre `inicializar_db.py` para refrescar."

    badge = BADGES_PRIORIDAD.get(c.get("prioridad"), "")
    cabecera = [
        f"🛣️ *Ficha completa — NOG {c.get('nog', 'N/A')}*",
        f"Proyecto: {c.get('titulo') or 'Sin título'}",
        f"Entidad: {c.get('entidad') or 'No especificada'}",
    ]
    if badge:
        cabecera.append(f"Prioridad: {badge}")
    cabecera.append(
        f"Modalidad: {c.get('modalidad') or 'No especificada'}  ·  "
        f"Estado: {c.get('estado') or 'No especificado'}"
    )

    if not c.get("fecha_extraccion"):
        cabecera.append("")
        cabecera.append(
            "⚠️ Este NOG aún no tiene extracción de bases. "
            f"Corre `.venv/bin/python extraer_volumen.py --nog {c.get('nog')}` "
            "para sacar volúmenes, fechas y plazos."
        )
        link = c.get("link")
        if link:
            cabecera.append(f"🔗 {link}")
        return "\n".join(cabecera)

    secciones = ["\n".join(cabecera)]

    # Alcance y volúmenes
    bloque_alcance = ["*📐 Alcance y volumen*"]
    resumen = c.get("resumen_alcance")
    if resumen:
        bloque_alcance.append(f"Alcance: {resumen}")
    magnitudes = []
    for valor, unidad in [
        (c.get("m2_total"), "m²"),
        (c.get("ml_total"), "ml"),
        (c.get("m3_total"), "m³"),
    ]:
        formateado = formatear_volumen(valor, unidad)
        if formateado:
            magnitudes.append(formateado)
    if magnitudes:
        bloque_alcance.append("Totales: " + "  ·  ".join(magnitudes))
    confianza = c.get("confianza_volumen")
    if confianza:
        bloque_alcance.append(f"Confianza extracción: {confianza}")
    notas = c.get("notas_extraccion")
    if notas:
        bloque_alcance.append(f"Notas: {notas}")
    secciones.append("\n".join(bloque_alcance))

    # Fechas críticas
    fechas_visibles = {
        "Visita técnica": c.get("visita_tecnica"),
        "Lugar de visita": c.get("lugar_visita"),
        "Recepción de ofertas": c.get("recepcion_ofertas"),
        "Apertura de plicas": c.get("apertura_plicas"),
        "Consultas/aclaraciones": c.get("consultas_aclaraciones"),
    }
    fechas_con_valor = [(k, v) for k, v in fechas_visibles.items() if v]
    if fechas_con_valor:
        bloque_fechas = ["*📅 Fechas críticas*"]
        for label, valor in fechas_con_valor:
            bloque_fechas.append(f"{label}: {valor}")
        secciones.append("\n".join(bloque_fechas))

    # Plazos
    plazos_visibles = {
        "Plazo de ejecución": (c.get("plazo_ejecucion_dias"), "días calendario"),
        "Vigencia de oferta": (c.get("vigencia_oferta_dias"), "días"),
        "Tiempo de garantía de obra": (c.get("tiempo_garantia_meses"), "meses"),
    }
    plazos_con_valor = [(k, v, u) for k, (v, u) in plazos_visibles.items() if v]
    if plazos_con_valor:
        bloque_plazos = ["*⏱ Plazos*"]
        for label, valor, unidad in plazos_con_valor:
            bloque_plazos.append(f"{label}: {valor} {unidad}")
        secciones.append("\n".join(bloque_plazos))

    # Garantías requeridas
    try:
        garantias = json.loads(c.get("garantias_json") or "[]")
    except json.JSONDecodeError:
        garantias = []
    if garantias:
        bloque_g = ["*🛡 Garantías requeridas*"]
        for g in garantias:
            partes = [g.get("tipo", "").capitalize()]
            if g.get("porcentaje"):
                partes.append(f"{g['porcentaje']}%")
            if g.get("monto"):
                partes.append(formatear_monto(g["monto"]))
            if g.get("notas"):
                partes.append(f"({g['notas']})")
            bloque_g.append("  - " + " · ".join(p for p in partes if p))
        secciones.append("\n".join(bloque_g))

    # Requisitos de oferente
    try:
        requisitos = json.loads(c.get("requisitos_oferente_json") or "[]")
    except json.JSONDecodeError:
        requisitos = []
    if requisitos:
        bloque_r = ["*📋 Requisitos clave para participar*"]
        for r in requisitos:
            bloque_r.append(f"  - {r}")
        secciones.append("\n".join(bloque_r))

    # Renglones clave
    try:
        renglones = json.loads(c.get("renglones_json") or "[]")
    except json.JSONDecodeError:
        renglones = []
    if renglones:
        bloque_re = ["*📊 Renglones clave de obra*"]
        for r in renglones:
            concepto = (r.get("concepto") or "")[:60]
            cantidad = r.get("cantidad")
            unidad = r.get("unidad", "")
            if cantidad is not None:
                bloque_re.append(f"  - {concepto:<60} {cantidad:>12} {unidad}")
            else:
                bloque_re.append(f"  - {concepto}")
        secciones.append("\n".join(bloque_re))

    # Publicación y link
    pie = [
        "*📎 Referencias*",
        f"Publicación: {formatear_fecha(c.get('fecha_publicacion'))}  ·  "
        f"Cierre: {formatear_fecha(c.get('fecha_cierre'))}",
    ]
    link = c.get("link")
    if link:
        pie.append(f"🔗 {link}")
    pie.append(f"Extracción: {c.get('fecha_extraccion')}")
    secciones.append("\n".join(pie))

    return "\n\n".join(secciones)


def consultar_ficha_nog(nog, formato="reporte"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM concursos WHERE nog = ?", (nog,))
    row = cursor.fetchone()
    columnas = [d[0] for d in cursor.description] if cursor.description else []
    conn.close()

    c = dict(zip(columnas, row)) if row else None

    if formato == "json":
        print(json.dumps(c, indent=2, ensure_ascii=False, default=str))
    else:
        print(construir_ficha(c))


def consultar_concursos(
    limite=5,
    desde="2026-05-01",
    estado="vigente",
    prioridades=("alta", "media"),
    formato="reporte",
):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    tiene_prioridad = columna_existe(cursor, "concursos", "prioridad")
    tiene_volumen = columna_existe(cursor, "concursos", "m2_total")

    campos = [
        "nog", "entidad", "titulo", "fecha_publicacion", "fecha_cierre",
        "estado", "modalidad", "unidad_objetivo", "monto", "link",
    ]
    if tiene_prioridad:
        campos.append("prioridad")
    if tiene_volumen:
        campos.extend([
            "m2_total", "ml_total", "m3_total",
            "resumen_alcance", "confianza_volumen",
        ])

    filtros = ["LOWER(COALESCE(estado, '')) = ?"]
    parametros = [normalizar_estado(estado)]

    if desde:
        filtros.append("date(substr(fecha_publicacion, 1, 10)) >= date(?)")
        parametros.append(desde)

    if tiene_prioridad and prioridades:
        filtros.append(
            "LOWER(COALESCE(prioridad, 'baja')) IN ("
            + ", ".join(["?"] * len(prioridades)) + ")"
        )
        parametros.extend(p.lower() for p in prioridades)

    where_sql = f"WHERE {' AND '.join(filtros)}"

    if tiene_volumen:
        order_sql = """
        ORDER BY
            CASE WHEN m2_total IS NULL OR m2_total = 0 THEN 1 ELSE 0 END,
            COALESCE(m2_total, 0) DESC,
            COALESCE(monto, 0) DESC,
            CASE LOWER(COALESCE(prioridad, 'baja'))
                WHEN 'alta' THEN 0
                WHEN 'media' THEN 1
                ELSE 2
            END
        """
    else:
        order_sql = """
        ORDER BY
            COALESCE(monto, 0) DESC,
            CASE LOWER(COALESCE(prioridad, 'baja'))
                WHEN 'alta' THEN 0
                WHEN 'media' THEN 1
                ELSE 2
            END
        """

    cursor.execute(
        f"""
        SELECT {', '.join(campos)}
        FROM concursos
        {where_sql}
        {order_sql}
        LIMIT ?
        """,
        (*parametros, limite),
    )

    resultados = cursor.fetchall()
    conn.close()

    lista_concursos = [dict(zip(campos, row)) for row in resultados]

    if formato == "json":
        print(json.dumps(lista_concursos, indent=2, ensure_ascii=False))
    else:
        print(construir_reporte(lista_concursos, desde, prioridades))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lector de base de datos para Claudio")
    parser.add_argument("--nog", help="Ficha completa de un NOG específico (incluye fechas, plazos, garantías, renglones)")
    parser.add_argument("--limite", type=int, default=5, help="Cantidad de proyectos a traer (listado)")
    parser.add_argument("--desde", default="2026-05-01", help="Fecha mínima de publicación, formato YYYY-MM-DD")
    parser.add_argument("--estado", default="vigente", help="Estado a consultar, por defecto vigente")
    parser.add_argument(
        "--prioridad",
        default="alta,media",
        help="CSV de prioridades a incluir: alta, media, baja o 'todas' (default: alta,media)",
    )
    parser.add_argument("--json", action="store_true", help="Imprime JSON crudo en lugar del reporte ejecutivo")
    args = parser.parse_args()

    if args.nog:
        consultar_ficha_nog(args.nog, formato="json" if args.json else "reporte")
    else:
        if args.prioridad.lower() == "todas":
            prioridades = ("alta", "media", "baja")
        else:
            prioridades = tuple(
                p.strip().lower() for p in args.prioridad.split(",") if p.strip()
            )

        consultar_concursos(
            limite=args.limite,
            desde=args.desde,
            estado=args.estado,
            prioridades=prioridades,
            formato="json" if args.json else "reporte",
        )
