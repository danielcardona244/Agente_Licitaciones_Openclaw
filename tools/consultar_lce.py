"""Consulta la Ley de Contrataciones del Estado y/o su Reglamento.

Documentos soportados:
  - Ley: Decreto 57-92 → referencias/lce/decreto-57-92.md
  - Reglamento: Acuerdo Gubernativo 122-2016 → referencias/lce/reglamento.md

Búsqueda por:
  - Número de artículo (incluye "Bis")
  - Palabras clave en cuerpo o título
  - Título romano (solo Ley; Reglamento tiene jerarquía simple)
  - Listado completo agrupado por documento

Uso:
  .venv/bin/python tools/consultar_lce.py --articulo 65
  .venv/bin/python tools/consultar_lce.py --articulo 56 --documento reglamento
  .venv/bin/python tools/consultar_lce.py --articulo "25 Bis"
  .venv/bin/python tools/consultar_lce.py --buscar fianza            # ambos documentos
  .venv/bin/python tools/consultar_lce.py --buscar fianza -d ley     # solo Ley
  .venv/bin/python tools/consultar_lce.py --titulo V
  .venv/bin/python tools/consultar_lce.py --lista
"""

import argparse
import json
import re
import sys
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent

DOCUMENTOS = {
    "ley": {
        "ruta": WORKSPACE_DIR / "referencias" / "lce" / "decreto-57-92.md",
        "etiqueta": "Ley (Decreto 57-92)",
        "abreviatura": "LCE",
    },
    "reglamento": {
        "ruta": WORKSPACE_DIR / "referencias" / "lce" / "reglamento.md",
        "etiqueta": "Reglamento (Acuerdo 122-2016)",
        "abreviatura": "RLCE",
    },
}


def parsear_md(texto):
    """Parsea un .md con la convención TÍTULO/CAPÍTULO/Artículo."""
    articulos = []
    lineas = texto.splitlines()

    titulo_romano_actual = None
    capitulo_actual = None
    articulo_actual = None
    cuerpo_acumulado = []

    re_titulo_romano = re.compile(r"^##\s+T[IÍ]TULO\s+([IVX]+)\b\s*(?:—\s*(.*))?$", re.IGNORECASE)
    re_capitulo_md = re.compile(r"^##\s+CAP[IÍ]TULO\s+([IVX]+|[ÚU]NICO)\b\s*(?:—\s*(.*))?$", re.IGNORECASE)
    re_subcapitulo = re.compile(r"^###\s+CAP[IÍ]TULO\s+([IVX]+|[ÚU]NICO)\b\s*(?:—\s*(.*))?$", re.IGNORECASE)
    re_articulo = re.compile(r"^###\s+Artículo\s+(\d+(?:\s*Bis)?)\.\s*(.*)$", re.IGNORECASE)

    def cerrar_articulo():
        if articulo_actual:
            articulo_actual["cuerpo"] = "\n".join(cuerpo_acumulado).strip()
            articulos.append(articulo_actual)

    for linea in lineas:
        m_titulo = re_titulo_romano.match(linea)
        if m_titulo:
            cerrar_articulo()
            articulo_actual = None
            cuerpo_acumulado = []
            titulo_romano_actual = (m_titulo.group(1).upper(), (m_titulo.group(2) or "").strip())
            capitulo_actual = None
            continue

        m_cap = re_capitulo_md.match(linea) or re_subcapitulo.match(linea)
        if m_cap:
            cerrar_articulo()
            articulo_actual = None
            cuerpo_acumulado = []
            capitulo_actual = (m_cap.group(1).upper(), (m_cap.group(2) or "").strip())
            continue

        m_art = re_articulo.match(linea)
        if m_art:
            cerrar_articulo()
            numero = re.sub(r"\s+", " ", m_art.group(1)).strip()
            articulo_actual = {
                "numero": numero,
                "titulo_articulo": m_art.group(2).strip(),
                "titulo_romano": titulo_romano_actual,
                "capitulo": capitulo_actual,
            }
            cuerpo_acumulado = []
            continue

        if articulo_actual is not None:
            cuerpo_acumulado.append(linea)

    cerrar_articulo()
    return articulos


def cargar_documentos(documento_filtro):
    """Carga uno o varios documentos según --documento. Devuelve dict {clave: [articulos]}."""
    if documento_filtro == "todos":
        claves = list(DOCUMENTOS.keys())
    else:
        if documento_filtro not in DOCUMENTOS:
            print(f"❌ Documento desconocido: '{documento_filtro}'. Opciones: ley, reglamento, todos.")
            sys.exit(1)
        claves = [documento_filtro]

    resultado = {}
    for clave in claves:
        ruta = DOCUMENTOS[clave]["ruta"]
        if not ruta.exists():
            print(f"⚠️ {DOCUMENTOS[clave]['etiqueta']}: {ruta} no encontrado, se omite.")
            continue
        resultado[clave] = parsear_md(ruta.read_text(encoding="utf-8"))
    return resultado


def normalizar(s):
    if not s:
        return ""
    s = s.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        s = s.replace(a, b)
    return s


def buscar_articulo(articulos, numero):
    clave_norm = normalizar(numero.replace("bis", "").strip())
    es_bis = "bis" in numero.lower()
    for art in articulos:
        num_norm = normalizar(art["numero"].replace("bis", "").strip())
        art_es_bis = "bis" in art["numero"].lower()
        if num_norm == clave_norm and art_es_bis == es_bis:
            return art
    return None


def buscar_palabra(articulos, keyword):
    kw = normalizar(keyword)
    return [a for a in articulos if kw in normalizar(a["titulo_articulo"] + " " + a["cuerpo"])]


def formatear_articulo(art, etiqueta_doc):
    cabecera_jerarquia = ""
    if art.get("titulo_romano"):
        cabecera_jerarquia = f"📜 *{etiqueta_doc} · Título {art['titulo_romano'][0]}"
        if art["titulo_romano"][1]:
            cabecera_jerarquia += f" — {art['titulo_romano'][1]}"
        cabecera_jerarquia += "*"
        if art.get("capitulo"):
            cabecera_jerarquia += f"  ·  Capítulo {art['capitulo'][0]}"
            if art["capitulo"][1]:
                cabecera_jerarquia += f" — {art['capitulo'][1]}"
    else:
        cabecera_jerarquia = f"📜 *{etiqueta_doc}*"
    encabezado = f"*Artículo {art['numero']}. {art['titulo_articulo']}*"
    return f"{cabecera_jerarquia}\n\n{encabezado}\n\n{art['cuerpo']}".strip()


def main():
    parser = argparse.ArgumentParser(
        description="Consulta la Ley de Contrataciones del Estado y/o su Reglamento."
    )
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--articulo", "-a", help="Número de artículo (ej. 65, '25 Bis')")
    grupo.add_argument("--buscar", "-b", help="Palabra clave a buscar en cuerpo y título")
    grupo.add_argument("--titulo", "-t", help="Filtrar por título romano (solo aplicable a la Ley)")
    grupo.add_argument("--lista", "-l", action="store_true", help="Lista todos los artículos")
    parser.add_argument(
        "--documento", "-d",
        default="todos",
        choices=["ley", "reglamento", "todos"],
        help="A qué documento consultar (default: todos)",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON crudo")
    args = parser.parse_args()

    docs = cargar_documentos(args.documento)
    if not docs:
        print("❌ No se cargó ningún documento.")
        sys.exit(1)

    if args.articulo:
        encontrados = []
        for clave, articulos in docs.items():
            art = buscar_articulo(articulos, args.articulo)
            if art:
                art_copy = {**art, "_documento": clave}
                encontrados.append(art_copy)
        if not encontrados:
            print(f"⚠️ Artículo '{args.articulo}' no encontrado en {args.documento}.")
            sys.exit(1)
        if args.json:
            print(json.dumps(encontrados, indent=2, ensure_ascii=False))
        else:
            for art in encontrados:
                print(formatear_articulo(art, DOCUMENTOS[art["_documento"]]["etiqueta"]))
                if len(encontrados) > 1:
                    print("\n" + "─" * 60 + "\n")

    elif args.buscar:
        todos = []
        for clave, articulos in docs.items():
            for art in buscar_palabra(articulos, args.buscar):
                todos.append({**art, "_documento": clave})
        if not todos:
            print(f"⚠️ Sin coincidencias para '{args.buscar}'.")
            sys.exit(0)
        if args.json:
            print(json.dumps(todos, indent=2, ensure_ascii=False))
        else:
            print(f"📚 *Resultados para '{args.buscar}' — {len(todos)} artículo(s)*\n")
            for art in todos:
                abrev = DOCUMENTOS[art["_documento"]]["abreviatura"]
                print(f"  [{abrev}] Art. {art['numero']}: {art['titulo_articulo']}")
            print(f"\nUsa `--articulo NÚMERO [--documento ley|reglamento]` para ver un artículo completo.")

    elif args.titulo:
        romano = args.titulo.upper().strip()
        encontrados = []
        for clave, articulos in docs.items():
            for art in articulos:
                if art.get("titulo_romano") and art["titulo_romano"][0] == romano:
                    encontrados.append({**art, "_documento": clave})
        if not encontrados:
            print(f"⚠️ Título romano '{romano}' no encontrado.")
            sys.exit(1)
        if args.json:
            print(json.dumps(encontrados, indent=2, ensure_ascii=False))
        else:
            doc_actual = None
            for art in encontrados:
                if art["_documento"] != doc_actual:
                    doc_actual = art["_documento"]
                    print(f"\n📜 *{DOCUMENTOS[doc_actual]['etiqueta']}*")
                print(f"  • Art. {art['numero']}: {art['titulo_articulo']}")

    elif args.lista:
        if args.json:
            payload = {clave: arts for clave, arts in docs.items()}
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            for clave, articulos in docs.items():
                etiqueta = DOCUMENTOS[clave]["etiqueta"]
                print(f"\n📜 *{etiqueta}*  ·  Total: {len(articulos)} artículos\n")
                for art in articulos:
                    print(f"  • Art. {art['numero']}: {art['titulo_articulo']}")


if __name__ == "__main__":
    main()
