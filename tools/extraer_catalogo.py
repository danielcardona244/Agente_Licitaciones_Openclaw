"""Extrae un catálogo de renglones COVIAL desde una oferta histórica (.xlsx).

Lee cada hoja de integración de precio unitario y produce un JSON estructurado
que sirve de base de precios para `generar_oferta.py`.

Estructura del JSON producido (data/catalogo_renglones.json):

{
  "_meta": {
    "fuente": "<archivo origen>",
    "generado": "<ISO timestamp>",
    "total_renglones": N
  },
  "renglones": {
    "Co 601.07.02.A": {
      "descripcion": "Suministro y Aplicación de Pintura Termoplástica...",
      "unidad": "ml",
      "rendimiento": 1500,
      "rendimiento_unidad": "ml/día",
      "equipo": [
        {"cantidad": 1, "descripcion": "Máquina autopropulsada...", "horas": 8, "costo_hora": 380}
      ],
      "mano_obra": [
        {"cantidad": 1, "descripcion": "Encargado de cuadrilla", "horas": 8, "costo_hora": 80}
      ],
      "materiales": [
        {"cantidad": 900, "descripcion": "Material termoplástico (lb)", "precio_unitario": 20, "unidad": "lb"}
      ],
      "precio_unitario_referencia": 30.0,
      "hoja_fuente": "601_07_02_A"
    },
    ...
  }
}

Uso:
  .venv/bin/python tools/extraer_catalogo.py \
      --origen ofertas_historicas/Oferta_SG-002-2026_OYL.xlsx \
      --salida data/catalogo_renglones.json
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

WORKSPACE_DIR = Path(__file__).resolve().parent.parent


def es_hoja_renglon(nombre):
    """Detecta nombres de hoja tipo '601_07_02_A' o '602_02_a_01' (códigos COVIAL)."""
    return bool(re.match(r"^\d{3}(_\w+)*$", nombre))


def codigo_desde_hoja(nombre_hoja, codigo_b7):
    """Si la hoja trae el código en B7 ('Co 601.07.02.A') lo prefiere; si no, lo deriva del nombre."""
    if codigo_b7 and isinstance(codigo_b7, str):
        return codigo_b7.strip()
    return "Co " + nombre_hoja.replace("_", ".")


def numero(valor):
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return valor
    try:
        return float(str(valor).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def extraer_bloque_lineas(ws, fila_inicio, fila_fin, cols=("A", "B", "F", "G", "H")):
    """Extrae filas no vacías entre fila_inicio y fila_fin con columnas dadas."""
    bloques = []
    for fila in range(fila_inicio, fila_fin + 1):
        valores = {col: ws[f"{col}{fila}"].value for col in cols}
        if not any(v is not None for v in valores.values()):
            continue
        bloques.append((fila, valores))
    return bloques


def extraer_renglon(ws):
    """Parsea una hoja de integración de precio unitario."""
    codigo = codigo_desde_hoja(ws.title, texto(ws["B7"].value))
    return {
        "codigo": codigo,
        "descripcion": texto(ws["B8"].value),
        "unidad": texto(ws["B9"].value),
        "rendimiento": numero(ws["B12"].value),
        "rendimiento_unidad": texto(ws["C12"].value),
        "equipo": parsear_equipo_o_mo(ws, fila_inicio=16, fila_fin=19),
        "mano_obra": parsear_equipo_o_mo(ws, fila_inicio=24, fila_fin=27),
        "materiales": parsear_materiales(ws, fila_inicio=34, fila_fin=37),
        "precio_unitario_referencia": evaluar_precio_unitario(ws),
        "hoja_fuente": ws.title,
    }


def parsear_equipo_o_mo(ws, fila_inicio, fila_fin):
    """Equipo y MO comparten estructura: Cant·Desc·Hrs·Costo/Hr·SubTotal en A,B,F,G,H."""
    items = []
    for fila in range(fila_inicio, fila_fin + 1):
        cant = numero(ws[f"A{fila}"].value)
        desc = texto(ws[f"B{fila}"].value)
        horas = numero(ws[f"F{fila}"].value)
        costo_hora = numero(ws[f"G{fila}"].value)
        if not desc and not cant:
            continue
        items.append({
            "cantidad": cant,
            "descripcion": desc,
            "horas": horas,
            "costo_hora": costo_hora,
        })
    return items


def parsear_materiales(ws, fila_inicio, fila_fin):
    """Materiales: Cant·Desc·P.U.·Unidad·SubTotal en A,B,F,G,H."""
    items = []
    for fila in range(fila_inicio, fila_fin + 1):
        cant = numero(ws[f"A{fila}"].value)
        desc = texto(ws[f"B{fila}"].value)
        pu = numero(ws[f"F{fila}"].value)
        unidad = texto(ws[f"G{fila}"].value)
        if not desc and not cant:
            continue
        items.append({
            "cantidad": cant,
            "descripcion": desc,
            "precio_unitario": pu,
            "unidad": unidad,
        })
    return items


def evaluar_precio_unitario(ws):
    """Reconstruye el P.U. calculado a partir de los componentes (no de la fórmula Excel)."""
    total_equipo = sum(
        (it["cantidad"] or 0) * (it["horas"] or 0) * (it["costo_hora"] or 0)
        for it in parsear_equipo_o_mo(ws, 16, 19)
    )
    total_mo = sum(
        (it["cantidad"] or 0) * (it["horas"] or 0) * (it["costo_hora"] or 0)
        for it in parsear_equipo_o_mo(ws, 24, 27)
    )
    herramienta = 0.05 * total_mo
    total_mat = sum(
        (it["cantidad"] or 0) * (it["precio_unitario"] or 0)
        for it in parsear_materiales(ws, 34, 37)
    )
    costo_directo = total_mo + herramienta + total_mat
    indirectos = 0.25 * costo_directo
    subtotal = costo_directo + indirectos + total_equipo
    total_con_iva = subtotal * 1.12
    rendimiento = numero(ws["B12"].value) or 1
    if rendimiento == 0:
        return None
    return round(total_con_iva / rendimiento, 2)


def precio_unitario_de_anexo8(wb):
    """Lee la ANEXO 8 para tomar los P.U. tal como aparecen en la oferta presentada."""
    if "ANEXO 8" not in wb.sheetnames:
        return {}
    ws = wb["ANEXO 8"]
    precios = {}
    for fila in range(12, ws.max_row + 1):
        codigo = texto(ws[f"A{fila}"].value)
        pu = numero(ws[f"E{fila}"].value)
        if codigo and codigo.startswith("Co ") and pu is not None:
            precios[codigo] = pu
    return precios


def main():
    parser = argparse.ArgumentParser(description="Extrae catálogo COVIAL desde una oferta .xlsx")
    parser.add_argument("--origen", required=True, help="Ruta al .xlsx de la oferta histórica")
    parser.add_argument(
        "--salida",
        default=str(WORKSPACE_DIR / "data" / "catalogo_renglones.json"),
        help="Ruta de salida del JSON (default: data/catalogo_renglones.json)",
    )
    args = parser.parse_args()

    origen = Path(args.origen)
    if not origen.is_absolute():
        origen = WORKSPACE_DIR / origen
    if not origen.exists():
        print(f"❌ No existe: {origen}")
        sys.exit(1)

    print(f"📥 Leyendo {origen.name}...")
    wb = load_workbook(origen, data_only=False)

    pu_anexo8 = precio_unitario_de_anexo8(wb)
    print(f"  · {len(pu_anexo8)} precios unitarios en ANEXO 8")

    renglones = {}
    for nombre_hoja in wb.sheetnames:
        if not es_hoja_renglon(nombre_hoja):
            continue
        ws = wb[nombre_hoja]
        try:
            datos = extraer_renglon(ws)
        except Exception as exc:
            print(f"  ⚠️ {nombre_hoja}: error parseando — {exc}")
            continue

        # Si la ANEXO 8 tiene el P.U. final ofertado, lo usamos en lugar del calculado
        if datos["codigo"] in pu_anexo8:
            datos["precio_unitario_final"] = pu_anexo8[datos["codigo"]]

        renglones[datos["codigo"]] = datos
        print(f"  ✅ {datos['codigo']:20s}  {datos['descripcion'][:50]}")

    salida = Path(args.salida)
    if not salida.is_absolute():
        salida = WORKSPACE_DIR / salida
    salida.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "_meta": {
            "fuente": str(origen.relative_to(WORKSPACE_DIR)),
            "generado": datetime.utcnow().isoformat(timespec="seconds"),
            "total_renglones": len(renglones),
            "nota": "Catálogo derivado de oferta histórica. Reemplazar con catálogo oficial cuando esté disponible.",
        },
        "renglones": renglones,
    }
    salida.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n📊 {len(renglones)} renglones extraídos → {salida.relative_to(WORKSPACE_DIR)}")


if __name__ == "__main__":
    main()
