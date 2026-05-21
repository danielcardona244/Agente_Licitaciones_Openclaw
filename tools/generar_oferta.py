"""Genera un borrador de oferta .xlsx siguiendo el formato OYL.

Combina:
  - Datos del NOG (de data/guatecompras_local.db, ya extraído por extraer_volumen.py)
  - Catálogo de precios (data/catalogo_renglones.json o referencias/catalogo_renglones_covial.json si existe)
  - Datos del oferente proporcionados por CLI (no se persisten — varían por oferta)

Salida:
  - data/ofertas_generadas/Oferta_{nog}_{empresa_slug}_{fecha}.xlsx
  - Hoja ANEXO 8 con cuadro resumen
  - N hojas de integración de precio unitario (una por renglón que coincida con catálogo)
  - Hoja PENDIENTES si hay renglones sin match (precio = [FALTA AGREGAR])

Uso:
  .venv/bin/python tools/generar_oferta.py \\
      --nog 30098408 \\
      --empresa "ORELLANA Y LEÓN CAPITAL, S.A." \\
      --nit "1234567-8" \\
      --representante "Rodrigo García Orellana" \\
      --direccion "5ta calle 1-23 zona 10, Guatemala" \\
      --telefono "5555-5555" \\
      --correo "ofertas@oyl.gt" \\
      --superintendente "Ing. Juan Pérez" \\
      --colegiado "12345" \\
      --tel-sup "5555-6666" \\
      --tiempo-meses 7

Datos opcionales no provistos → quedan como [FALTA: descripción] en el .xlsx.
"""

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = WORKSPACE_DIR / "data" / "guatecompras_local.db"

# Catálogos en orden de prioridad. El oficial gana sobre el local cuando exista.
CATALOGOS = [
    WORKSPACE_DIR / "referencias" / "catalogo_renglones_covial.json",
    WORKSPACE_DIR / "data" / "catalogo_renglones.json",
]
SALIDA_DIR = WORKSPACE_DIR / "data" / "ofertas_generadas"

# Paleta visual replicada exactamente del template OYL
COLOR_AZUL_OSCURO = "1F4E78"   # Encabezados de sección y de tabla principal
COLOR_AZUL_CLARO = "DDEBF7"    # Sub-encabezados y totales intermedios
COLOR_AMARILLO_ORO = "FFC000"  # Total final ofertado / Precio unitario calculado
COLOR_BLANCO = "FFFFFF"
COLOR_ROJO_CLARO = "FFD7D7"    # Marca [FALTA AGREGAR]

HEADER_FILL = PatternFill("solid", fgColor=COLOR_AZUL_OSCURO)        # azul oscuro con texto blanco
SUBHEADER_FILL = PatternFill("solid", fgColor=COLOR_AZUL_CLARO)      # azul claro para sub-headers
TOTAL_FILL = PatternFill("solid", fgColor=COLOR_AMARILLO_ORO)        # amarillo dorado para total final
SUBTOTAL_FILL = PatternFill("solid", fgColor=COLOR_AZUL_CLARO)       # azul claro para SUBTOTAL/IVA
FALTA_FILL = PatternFill("solid", fgColor=COLOR_ROJO_CLARO)

FUENTE_BASE = "Arial"
FONT_HEADER = Font(name=FUENTE_BASE, size=10, bold=True, color=COLOR_BLANCO)
FONT_SUBHEADER = Font(name=FUENTE_BASE, size=10, bold=True)
FONT_TITULO_PROYECTO = Font(name=FUENTE_BASE, size=14, bold=True, color=COLOR_AZUL_OSCURO)
FONT_NORMAL = Font(name=FUENTE_BASE, size=10)
FONT_BOLD = Font(name=FUENTE_BASE, size=10, bold=True)
FONT_TOTAL = Font(name=FUENTE_BASE, size=10, bold=True)

BORDER_THIN = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_WRAP = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")

PLACEHOLDER_FALTA = "[FALTA AGREGAR]"


def slugify(texto):
    """Convierte texto a slug seguro para nombre de archivo."""
    s = unicodedata.normalize("NFKD", texto or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:40] or "Empresa"


def cargar_nog(nog):
    """Lee el NOG completo desde la DB (todas las columnas)."""
    if not DB_PATH.exists():
        print(f"❌ DB no encontrada: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM concursos WHERE nog = ?", (nog,))
    row = cursor.fetchone()
    if not row:
        print(f"❌ NOG {nog} no encontrado en la DB.")
        sys.exit(1)
    columnas = [d[0] for d in cursor.description]
    conn.close()
    return dict(zip(columnas, row))


def cargar_catalogo():
    """Carga el catálogo de precios. Si existe el oficial, gana sobre el local."""
    combinado = {}
    for ruta in CATALOGOS:
        if not ruta.exists():
            continue
        try:
            payload = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"⚠️ {ruta.name}: error de JSON — {exc}")
            continue
        for codigo, datos in payload.get("renglones", {}).items():
            if codigo not in combinado:
                combinado[codigo] = datos
    return combinado


def normalizar(s):
    if not s:
        return ""
    s = s.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        s = s.replace(a, b)
    # Compactar espacios y quitar puntuación común
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detectar_codigo_covial(descripcion):
    """Intenta extraer un código COVIAL del estilo 'Co 601.07.02.A' del texto."""
    if not descripcion:
        return None
    m = re.search(r"\bCo\s+\d{3}(?:\.\d+|\.\w+)*", descripcion)
    if m:
        return m.group(0)
    return None


def buscar_por_alias(descripcion_nog, catalogo):
    """Busca el primer renglón del catálogo cuyos aliases coincidan (substring normalizado)."""
    desc_norm = normalizar(descripcion_nog)
    if not desc_norm:
        return None
    mejor_codigo = None
    mejor_score = 0
    for codigo, datos in catalogo.items():
        aliases = datos.get("aliases", []) or []
        for alias in aliases:
            alias_norm = normalizar(alias)
            if not alias_norm:
                continue
            # Coincidencia: alias contenido en la descripción del NOG
            if alias_norm in desc_norm:
                # Score = longitud del alias (más específico es mejor)
                score = len(alias_norm)
                if score > mejor_score:
                    mejor_score = score
                    mejor_codigo = codigo
    return mejor_codigo


def matchear_renglones(renglones_nog, catalogo):
    """Por cada renglón del NOG intenta encontrar match en el catálogo.
    Estrategia: (1) código COVIAL en descripción; (2) alias semántico.
    Devuelve (con_match, faltantes).
    """
    con_match = []
    faltantes = []
    for renglon in renglones_nog:
        descripcion = renglon.get("concepto", "") or ""

        codigo = detectar_codigo_covial(descripcion)
        if codigo and codigo in catalogo:
            con_match.append({
                "renglon_nog": renglon,
                "codigo": codigo,
                "catalogo": catalogo[codigo],
                "metodo_match": "codigo_covial",
            })
            continue

        codigo_alias = buscar_por_alias(descripcion, catalogo)
        if codigo_alias:
            con_match.append({
                "renglon_nog": renglon,
                "codigo": codigo_alias,
                "catalogo": catalogo[codigo_alias],
                "metodo_match": "alias",
            })
            continue

        faltantes.append({
            "renglon_nog": renglon,
            "codigo": codigo or "(sin código COVIAL detectado)",
        })
    return con_match, faltantes


def valor_o_placeholder(valor, etiqueta):
    if valor is None or valor == "":
        return f"[FALTA: {etiqueta}]"
    return valor


def construir_anexo8(wb, ctx):
    """Crea la hoja ANEXO 8 con cuadro resumen y datos del oferente."""
    ws = wb.create_sheet("ANEXO 8", 0)

    # Encabezado del proyecto (estilo OYL: Arial 14 negrita color azul oscuro)
    ws["A1"] = ctx["entidad"] or "[FALTA: entidad]"
    ws["A1"].font = FONT_TITULO_PROYECTO
    ws["A2"] = "ANEXO No. 8"
    ws["A2"].font = FONT_BOLD
    ws["A3"] = f"PROYECTO {ctx['nog']} — {ctx['titulo']}"
    ws["A3"].font = FONT_TITULO_PROYECTO

    # Encabezado de la tabla (fila 11): fondo azul oscuro, texto blanco
    headers = ["RENGLÓN", "DESCRIPCIÓN DEL RENGLÓN", "UNIDAD", "CANTIDAD", "PRECIO UNITARIO", "MONTO"]
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=11, column=col, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER_THIN

    # Filas de renglones
    fila = 12
    for entrada in ctx["renglones_oferta"]:
        for col_idx in range(1, 7):
            ws.cell(row=fila, column=col_idx).font = FONT_NORMAL
            ws.cell(row=fila, column=col_idx).border = BORDER_THIN

        ws.cell(row=fila, column=1, value=entrada["codigo"])
        ws.cell(row=fila, column=2, value=entrada["descripcion"]).alignment = LEFT_WRAP
        ws.cell(row=fila, column=3, value=entrada["unidad"]).alignment = CENTER
        ws.cell(row=fila, column=4, value=entrada["cantidad"]).alignment = RIGHT

        if entrada["precio_unitario"] is None:
            c = ws.cell(row=fila, column=5, value=PLACEHOLDER_FALTA)
            c.fill = FALTA_FILL
            c.alignment = CENTER
            c.font = Font(name=FUENTE_BASE, size=10, bold=True, color="990000")
            ws.cell(row=fila, column=6, value=PLACEHOLDER_FALTA).fill = FALTA_FILL
        else:
            ws.cell(row=fila, column=5, value=entrada["precio_unitario"]).alignment = RIGHT
            ws.cell(row=fila, column=5).number_format = '"Q"#,##0.00'
            ws.cell(row=fila, column=6, value=f"=D{fila}*E{fila}").alignment = RIGHT
            ws.cell(row=fila, column=6).number_format = '"Q"#,##0.00'
        fila += 1

    ultima_fila_tabla = fila - 1

    # Totales: SUBTOTAL e IVA con fondo azul claro; TOTAL FINAL con fondo amarillo dorado
    if any(e["precio_unitario"] is not None for e in ctx["renglones_oferta"]):
        fila += 1
        ws.cell(row=fila, column=1, value="SUBTOTAL (sin IVA)").font = FONT_BOLD
        ws.cell(row=fila, column=1).fill = SUBTOTAL_FILL
        ws.cell(row=fila, column=6, value=f"=SUM(F12:F{ultima_fila_tabla})/1.12").number_format = '"Q"#,##0.00'
        ws.cell(row=fila, column=6).font = FONT_BOLD
        ws.cell(row=fila, column=6).fill = SUBTOTAL_FILL

        fila += 1
        ws.cell(row=fila, column=1, value="IVA 12% (ya incluido en precios unitarios)").font = FONT_BOLD
        ws.cell(row=fila, column=1).fill = SUBTOTAL_FILL
        ws.cell(row=fila, column=6, value=f"=SUM(F12:F{ultima_fila_tabla})-(SUM(F12:F{ultima_fila_tabla})/1.12)").number_format = '"Q"#,##0.00'
        ws.cell(row=fila, column=6).font = FONT_BOLD
        ws.cell(row=fila, column=6).fill = SUBTOTAL_FILL

        fila += 1
        ws.cell(row=fila, column=1, value="PRECIO TOTAL OFERTADO (CON IVA INCLUIDO)").font = FONT_TOTAL
        ws.cell(row=fila, column=1).fill = TOTAL_FILL
        ws.cell(row=fila, column=6, value=f"=SUM(F12:F{ultima_fila_tabla})").number_format = '"Q"#,##0.00'
        ws.cell(row=fila, column=6).font = FONT_TOTAL
        ws.cell(row=fila, column=6).fill = TOTAL_FILL

    # Tiempo de ejecución
    fila += 2
    ws.cell(row=fila, column=1, value="TIEMPO DE EJECUCIÓN DEL PROYECTO:").font = FONT_BOLD
    ws.cell(row=fila, column=2, value=valor_o_placeholder(ctx["tiempo_ejecucion"], "tiempo de ejecución")).font = FONT_NORMAL

    # Información del proyecto (datos del oferente)
    fila += 2
    ws.cell(row=fila, column=1, value="INFORMACIÓN DEL PROYECTO:").font = FONT_BOLD
    info_oferente = [
        ("Empresa:", ctx["empresa"], "razón social"),
        ("Representante Legal:", ctx["representante"], "representante legal"),
        ("NIT:", ctx["nit"], "NIT"),
        ("Teléfonos:", ctx["telefono"], "teléfono"),
        ("Dirección:", ctx["direccion"], "dirección fiscal"),
        ("Correo electrónico:", ctx["correo"], "correo"),
        ("Superintendente:", ctx["superintendente"], "superintendente"),
        ("No. Colegiado:", ctx["colegiado"], "número de colegiado"),
        ("Teléfono Superintendente:", ctx["tel_sup"], "teléfono superintendente"),
    ]
    for etiqueta, valor, descripcion in info_oferente:
        fila += 1
        ws.cell(row=fila, column=1, value=etiqueta).font = FONT_BOLD
        celda_valor = ws.cell(row=fila, column=2, value=valor_o_placeholder(valor, descripcion))
        celda_valor.font = FONT_NORMAL
        if not valor:
            celda_valor.fill = FALTA_FILL

    # Anchos de columna
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 20


def construir_hoja_integracion(wb, entrada_match, ctx):
    """Crea una hoja de integración de precio unitario con estilo OYL."""
    cat = entrada_match["catalogo"]
    nombre_hoja = entrada_match["codigo"].replace("Co ", "").replace(".", "_").replace("(", "_").replace(")", "")[:31]
    ws = wb.create_sheet(nombre_hoja)

    # Encabezado del proyecto (Arial 14 azul oscuro)
    ws["B2"] = ctx["entidad"]
    ws["B2"].font = FONT_TITULO_PROYECTO
    ws["B3"] = "INTEGRACIÓN DE PRECIOS UNITARIOS"
    ws["B3"].font = FONT_BOLD

    # Metadata del renglón (etiquetas en bold, valores normal)
    for fila_idx, (etiqueta, valor) in [
        (5, ("Empresa:", ctx["empresa"] or "[FALTA: empresa]")),
        (6, ("Proyecto:", f"{ctx['nog']} — {ctx['titulo']}")),
        (7, ("Código:", entrada_match["codigo"])),
        (8, ("Renglón:", cat.get("descripcion", ""))),
        (9, ("Unidad:", cat.get("unidad", ""))),
        (10, ("Fecha:", datetime.now().strftime("%d/%m/%Y"))),
    ]:
        ws.cell(row=fila_idx, column=1, value=etiqueta).font = FONT_BOLD
        ws.cell(row=fila_idx, column=2, value=valor).font = FONT_NORMAL

    rendimiento = cat.get("rendimiento") or 1
    ws["A12"].value = "Rendimiento:"
    ws["A12"].font = FONT_BOLD
    ws["B12"].value = rendimiento
    ws["B12"].font = FONT_NORMAL
    ws["C12"].value = cat.get("rendimiento_unidad", "")
    ws["C12"].font = FONT_NORMAL

    # Helper para sub-encabezado de cada bloque (Cantidad/Descripción/Hrs./Costo Hora/Sub-Total)
    def render_subheader(row, etiquetas_pos):
        for col, h in etiquetas_pos:
            c = ws.cell(row=row, column=col, value=h)
            c.font = FONT_SUBHEADER
            c.fill = SUBHEADER_FILL
            c.alignment = CENTER

    # EQUIPO (filas 14-20)
    c = ws.cell(row=14, column=1, value="EQUIPO")
    c.font = FONT_HEADER
    c.fill = HEADER_FILL
    ws.merge_cells("A14:H14")
    render_subheader(15, [(1, "Cantidad"), (2, "Descripción"), (6, "Hrs."), (7, "Costo Hora"), (8, "Sub-Total")])
    for i, item in enumerate(cat.get("equipo", [])[:4]):
        fila = 16 + i
        for col in [1, 2, 6, 7, 8]:
            ws.cell(row=fila, column=col).font = FONT_NORMAL
        ws.cell(row=fila, column=1, value=item.get("cantidad")).alignment = CENTER
        ws.cell(row=fila, column=2, value=item.get("descripcion")).alignment = LEFT_WRAP
        ws.cell(row=fila, column=6, value=item.get("horas")).alignment = CENTER
        ws.cell(row=fila, column=7, value=item.get("costo_hora")).number_format = '"Q"#,##0.00'
        ws.cell(row=fila, column=8, value=f"=A{fila}*F{fila}*G{fila}").number_format = '"Q"#,##0.00'
    ws.cell(row=20, column=7, value="TOTAL EQUIPO").font = FONT_BOLD
    c = ws.cell(row=20, column=8, value="=SUM(H16:H19)")
    c.font = FONT_BOLD
    c.fill = SUBTOTAL_FILL
    c.number_format = '"Q"#,##0.00'

    # MANO DE OBRA (filas 22-28)
    c = ws.cell(row=22, column=1, value="MANO DE OBRA")
    c.font = FONT_HEADER
    c.fill = HEADER_FILL
    ws.merge_cells("A22:H22")
    render_subheader(23, [(1, "Cantidad"), (2, "Descripción"), (6, "Hrs."), (7, "Costo Hora"), (8, "Sub-Total")])
    for i, item in enumerate(cat.get("mano_obra", [])[:4]):
        fila = 24 + i
        for col in [1, 2, 6, 7, 8]:
            ws.cell(row=fila, column=col).font = FONT_NORMAL
        ws.cell(row=fila, column=1, value=item.get("cantidad")).alignment = CENTER
        ws.cell(row=fila, column=2, value=item.get("descripcion")).alignment = LEFT_WRAP
        ws.cell(row=fila, column=6, value=item.get("horas")).alignment = CENTER
        ws.cell(row=fila, column=7, value=item.get("costo_hora")).number_format = '"Q"#,##0.00'
        ws.cell(row=fila, column=8, value=f"=A{fila}*F{fila}*G{fila}").number_format = '"Q"#,##0.00'
    ws.cell(row=28, column=7, value="TOTAL M.O.").font = FONT_BOLD
    c = ws.cell(row=28, column=8, value="=SUM(H24:H27)")
    c.font = FONT_BOLD
    c.fill = SUBTOTAL_FILL
    c.number_format = '"Q"#,##0.00'

    # HERRAMIENTA (fila 30)
    ws.cell(row=30, column=1, value="HERRAMIENTA (5% MANO DE OBRA)").font = FONT_BOLD
    c = ws.cell(row=30, column=8, value="=0.05*H28")
    c.font = FONT_BOLD
    c.number_format = '"Q"#,##0.00'

    # MATERIALES (filas 32-38)
    c = ws.cell(row=32, column=1, value="MATERIALES")
    c.font = FONT_HEADER
    c.fill = HEADER_FILL
    ws.merge_cells("A32:H32")
    render_subheader(33, [(1, "Cantidad"), (2, "Descripción"), (6, "P.U."), (7, "Unidad"), (8, "Sub-Total")])
    for i, item in enumerate(cat.get("materiales", [])[:4]):
        fila = 34 + i
        for col in [1, 2, 6, 7, 8]:
            ws.cell(row=fila, column=col).font = FONT_NORMAL
        ws.cell(row=fila, column=1, value=item.get("cantidad")).alignment = CENTER
        ws.cell(row=fila, column=2, value=item.get("descripcion")).alignment = LEFT_WRAP
        ws.cell(row=fila, column=6, value=item.get("precio_unitario")).number_format = '"Q"#,##0.00'
        ws.cell(row=fila, column=7, value=item.get("unidad")).alignment = CENTER
        ws.cell(row=fila, column=8, value=f"=A{fila}*F{fila}").number_format = '"Q"#,##0.00'
    ws.cell(row=38, column=7, value="TOTAL MAT.").font = FONT_BOLD
    c = ws.cell(row=38, column=8, value="=SUM(H34:H37)")
    c.font = FONT_BOLD
    c.fill = SUBTOTAL_FILL
    c.number_format = '"Q"#,##0.00'

    # Cálculo final (filas 40-45)
    for fila, etiqueta, formula in [
        (40, "Total Costo Directo:", "=H28+H30+H38"),
        (41, "Costos Indirectos (25%):", "=0.25*H40"),
        (42, "Equipo:", "=H20"),
        (43, "Subtotal (sin IVA):", "=H40+H41+H42"),
        (44, "IVA (12%):", "=0.12*H43"),
        (45, "Total por jornada (con IVA):", "=H43+H44"),
    ]:
        ws.cell(row=fila, column=4, value=etiqueta).font = FONT_BOLD
        ws.cell(row=fila, column=4).alignment = RIGHT
        c = ws.cell(row=fila, column=8, value=formula)
        c.font = FONT_NORMAL
        c.number_format = '"Q"#,##0.00'

    # PRECIO UNITARIO FINAL (fila 47) — fondo amarillo dorado destacado
    ws.cell(row=47, column=6, value="PRECIO UNITARIO POR:").font = FONT_BOLD
    ws.cell(row=47, column=7, value=cat.get("unidad", "")).font = FONT_BOLD
    c = ws.cell(row=47, column=8, value=f"=H45/B12")
    c.font = FONT_TOTAL
    c.number_format = '"Q"#,##0.00'
    c.fill = TOTAL_FILL

    # Anchos
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 40
    for col in "CDEFGH":
        ws.column_dimensions[col].width = 14


def construir_hoja_pendientes(wb, faltantes):
    """Hoja PENDIENTES con la lista de renglones sin match en catálogo."""
    if not faltantes:
        return
    ws = wb.create_sheet("PENDIENTES")
    ws["A1"] = "RENGLONES SIN PRECIO UNITARIO — REQUIEREN COMPLEMENTO MANUAL"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A1"].fill = FALTA_FILL
    ws.merge_cells("A1:E1")
    ws["A3"] = "Estos renglones del NOG no se encontraron en el catálogo de precios. Hay que llenarlos manualmente antes de presentar la oferta."
    ws.merge_cells("A3:E3")
    ws["A3"].alignment = LEFT_WRAP

    headers = ["#", "Concepto detectado en bases", "Cantidad", "Unidad", "Código COVIAL"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=5, column=col, value=h)
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.border = BORDER_THIN

    for i, falt in enumerate(faltantes, start=1):
        r = falt["renglon_nog"]
        fila = 5 + i
        ws.cell(row=fila, column=1, value=i).border = BORDER_THIN
        ws.cell(row=fila, column=2, value=r.get("concepto", "")).border = BORDER_THIN
        ws.cell(row=fila, column=2).alignment = LEFT_WRAP
        ws.cell(row=fila, column=3, value=r.get("cantidad")).border = BORDER_THIN
        ws.cell(row=fila, column=4, value=r.get("unidad", "")).border = BORDER_THIN
        ws.cell(row=fila, column=5, value=falt["codigo"]).border = BORDER_THIN

    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 30


def main():
    parser = argparse.ArgumentParser(
        description="Genera borrador de oferta .xlsx para un NOG combinando DB + catálogo + datos del oferente."
    )
    parser.add_argument("--nog", required=True, help="NOG del proyecto")
    parser.add_argument("--empresa", default="", help="Razón social")
    parser.add_argument("--nit", default="", help="NIT")
    parser.add_argument("--representante", default="", help="Representante legal")
    parser.add_argument("--direccion", default="", help="Dirección fiscal")
    parser.add_argument("--telefono", default="", help="Teléfono de contacto")
    parser.add_argument("--correo", default="", help="Correo de notificación")
    parser.add_argument("--superintendente", default="", help="Superintendente propuesto")
    parser.add_argument("--colegiado", default="", help="Número de colegiado CIG")
    parser.add_argument("--tel-sup", default="", help="Teléfono del superintendente", dest="tel_sup")
    parser.add_argument("--tiempo-meses", type=int, default=None, help="Tiempo de ejecución en meses")
    parser.add_argument("--salida", default="", help="Ruta de salida (default: data/ofertas_generadas/...)")
    args = parser.parse_args()

    # 1. Cargar NOG
    nog_data = cargar_nog(args.nog)
    if not nog_data.get("fecha_extraccion"):
        print(f"⚠️ El NOG {args.nog} no tiene extracción de bases. Corre 'extraer_volumen.py --nog {args.nog}' primero.")
        sys.exit(1)

    renglones_nog = json.loads(nog_data.get("renglones_json") or "[]")
    if not renglones_nog:
        print(f"⚠️ El NOG {args.nog} no tiene renglones extraídos.")
        sys.exit(1)

    # 2. Cargar catálogo
    catalogo = cargar_catalogo()
    if not catalogo:
        print("⚠️ No se encontró catálogo. Todos los renglones quedarán como FALTA AGREGAR.")

    # 3. Match
    con_match, faltantes = matchear_renglones(renglones_nog, catalogo)

    # 4. Determinar tiempo de ejecución
    tiempo_ejecucion = None
    if args.tiempo_meses:
        tiempo_ejecucion = f"{args.tiempo_meses} MESES"
    elif nog_data.get("plazo_ejecucion_dias"):
        meses = round(nog_data["plazo_ejecucion_dias"] / 30)
        tiempo_ejecucion = f"{meses} MESES (estimado de {nog_data['plazo_ejecucion_dias']} días)"

    # 5. Construir contexto para los renderers
    renglones_oferta = []
    for entrada in con_match:
        r = entrada["renglon_nog"]
        cat = entrada["catalogo"]
        precio = (
            cat.get("precio_unitario_final")
            or cat.get("precio_unitario_referencia")
            or cat.get("precio_unitario_estimado")
        )
        renglones_oferta.append({
            "codigo": entrada["codigo"],
            "descripcion": cat.get("descripcion", r.get("concepto", "")),
            "unidad": cat.get("unidad", r.get("unidad", "")),
            "cantidad": r.get("cantidad"),
            "precio_unitario": precio,
        })
    for falt in faltantes:
        r = falt["renglon_nog"]
        renglones_oferta.append({
            "codigo": falt["codigo"],
            "descripcion": r.get("concepto", ""),
            "unidad": r.get("unidad", ""),
            "cantidad": r.get("cantidad"),
            "precio_unitario": None,  # marca de FALTA
        })

    ctx = {
        "nog": args.nog,
        "titulo": nog_data.get("titulo", ""),
        "entidad": nog_data.get("entidad", ""),
        "tiempo_ejecucion": tiempo_ejecucion,
        "empresa": args.empresa,
        "nit": args.nit,
        "representante": args.representante,
        "direccion": args.direccion,
        "telefono": args.telefono,
        "correo": args.correo,
        "superintendente": args.superintendente,
        "colegiado": args.colegiado,
        "tel_sup": args.tel_sup,
        "renglones_oferta": renglones_oferta,
    }

    # 6. Construir workbook
    wb = Workbook()
    wb.remove(wb.active)  # quitamos la hoja default
    construir_anexo8(wb, ctx)
    for entrada in con_match:
        construir_hoja_integracion(wb, entrada, ctx)
    construir_hoja_pendientes(wb, faltantes)

    # 7. Guardar
    if args.salida:
        salida = Path(args.salida)
    else:
        SALIDA_DIR.mkdir(parents=True, exist_ok=True)
        fecha = datetime.now().strftime("%Y%m%d")
        nombre = f"Oferta_{args.nog}_{slugify(args.empresa)}_{fecha}.xlsx"
        salida = SALIDA_DIR / nombre

    wb.save(salida)

    # 8. Reporte
    print(f"\n✅ Oferta generada: {salida.relative_to(WORKSPACE_DIR) if salida.is_relative_to(WORKSPACE_DIR) else salida}")
    print(f"   Renglones con precio:  {len(con_match)}")
    print(f"   Renglones [FALTA AGREGAR]: {len(faltantes)}")

    datos_faltantes = [
        etiqueta for etiqueta, valor in [
            ("empresa", args.empresa), ("nit", args.nit),
            ("representante", args.representante), ("dirección", args.direccion),
            ("teléfono", args.telefono), ("correo", args.correo),
            ("superintendente", args.superintendente), ("colegiado", args.colegiado),
            ("tel-sup", args.tel_sup),
        ] if not valor
    ]
    if datos_faltantes:
        print(f"   Datos del oferente FALTANTES: {', '.join(datos_faltantes)}")

    if faltantes:
        print(f"\n📋 Ver hoja PENDIENTES en el .xlsx para los {len(faltantes)} renglones que necesitan precio.")


if __name__ == "__main__":
    main()
