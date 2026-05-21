# Formato de Oferta — Plantilla OYL

Documentación técnica del formato `.xlsx` que Claudio debe replicar al generar borradores de oferta para licitaciones COVIAL/UECV/DGC/FSS. Basado en la oferta histórica `ofertas_historicas/Oferta_SG-002-2026_OYL.xlsx` (proyecto SG-002-2026 — Señalización General).

> **Audiencia:** Claudio y desarrolladores del agente. Este documento describe la estructura exacta de celdas, fórmulas y placeholders para que un script Python (`tools/generar_oferta.py`, pendiente) pueda producir un .xlsx idéntico al formato esperado por la entidad contratante.

---

## Visión general

La oferta es **un solo archivo `.xlsx` con N+1 hojas**, donde N = número de renglones de obra del proyecto:

- **1 hoja "ANEXO 8"** — Cuadro resumen de oferta con totales y datos del oferente.
- **N hojas de Integración de Precio Unitario** — Una por cada renglón con su desglose de equipo, mano de obra, materiales e indirectos.

Excepción: renglones tipo `Global` o `Unidad` administrativos (ej. `Co 625 Trabajos por Administración`, `Co 801 Dispositivos de Seguridad`) **no llevan hoja de integración** — su precio se fija directamente en la ANEXO 8.

---

## Hoja ANEXO 8 — Cuadro resumen de oferta

Dimensiones: `A1:F61` aprox. (varía con cantidad de renglones).

### Encabezado (filas 1-9)

| Celda | Contenido | Fuente del dato |
|---|---|---|
| A1 | `UNIDAD EJECUTORA DE CONSERVACIÓN VIAL -COVIAL-` (o la que aplique) | Bases del NOG (`unidad_objetivo` o `entidad` en DB) |
| A2 | `ANEXO No. 8` | Constante |
| A3 | `PROYECTO {código} — {nombre}` (ej. `SG-002-2026 — SEÑALIZACIÓN GENERAL`) | Bases del NOG |
| A5 | Etiquetas columna: `UBICACIÓN`, `DEPARTAMENTO`, `UG` | Constante |
| A6+ | Una fila por ubicación: descripción · departamento · número UG | Bases del NOG |

### Tabla principal (fila 11 = encabezado de tabla)

Columnas:

| Col | Encabezado | Tipo |
|---|---|---|
| A | RENGLÓN | Código `Co {clasificación}` (ej. `Co 601.07.02.A`) |
| B | DESCRIPCIÓN DEL RENGLÓN | Texto |
| C | UNIDAD | `ml`, `m²`, `m³`, `Unidad`, `Señal`, `Global` |
| D | CANTIDAD | Número (entero o decimal) |
| E | PRECIO UNITARIO | Número (Q) **— input del oferente** |
| F | MONTO | Fórmula `=D{fila}*E{fila}` |

A partir de la fila 12 hasta la fila N+11 (una por renglón).

### Totales (después de la última fila de la tabla)

| Fila | Etiqueta | Fórmula |
|---|---|---|
| N+12 | `SUBTOTAL (sin IVA)` | `=SUM(F12:F{N+11})/1.12` |
| N+13 | `IVA 12% (ya incluido en precios unitarios)` | `=SUM(F12:F{N+11})-(SUM(F12:F{N+11})/1.12)` |
| N+14 | `PRECIO TOTAL OFERTADO (CON IVA INCLUIDO)` | `=SUM(F12:F{N+11})` |

> **Nota importante:** los precios unitarios en E **YA incluyen el IVA**. Por eso el subtotal se obtiene dividiendo entre 1.12.

### Tiempo de ejecución (después de los totales, deja una fila en blanco)

| Celda | Contenido |
|---|---|
| A | `TIEMPO DE EJECUCIÓN DEL PROYECTO:` |
| B | `{N} MESES` (de las bases del NOG, campo `plazo_ejecucion_dias` ÷ 30) |

### Información del proyecto (datos del oferente — input runtime)

> **Importante:** los datos del oferente NO están guardados de forma persistente en el workspace. Cambian por oferta (Rodrigo opera con distintas empresas según el proyecto). Cuando le pide a Claudio una oferta para un NOG, **proporciona estos datos en el mismo mensaje**.

| Etiqueta (col A) | Valor (col B) | Origen |
|---|---|---|
| `Empresa:` | razón social completa | mensaje de Rodrigo a Claudio |
| `Representante Legal:` | nombre completo | mensaje |
| `NIT:` | NIT empresa | mensaje |
| `Teléfonos:` | teléfono de contacto | mensaje |
| `Dirección:` | dirección fiscal | mensaje |
| `Correo electrónico:` | correo de notificación | mensaje |
| `Superintendente:` | nombre Ing. Civil propuesto | mensaje |
| `No. Colegiado:` | colegiado activo CIG | mensaje |
| `Teléfono Superintendente:` | teléfono | mensaje |

Si en el mensaje falta algún dato, Claudio lo deja como `[FALTA: descripción del dato]` en el .xlsx generado y avisa a Rodrigo qué se quedó pendiente.

---

## Hojas de Integración de Precio Unitario

Una por cada renglón "real" (no aplica a globales/administrativos). Nombre de la hoja = código del renglón sin puntos (ej. `601_07_02_A` para `Co 601.07.02.A`).

Dimensiones típicas: `A2:H47` (45-47 filas).

### Encabezado (B2-B10)

| Celda | Contenido | Origen |
|---|---|---|
| B2 | `UNIDAD EJECUTORA DE CONSERVACIÓN VIAL -COVIAL-` | Bases del NOG |
| B3 | `INTEGRACIÓN DE PRECIOS UNITARIOS` | Constante |
| A5 / B5 | `Empresa:` / nombre empresa | OFERENTE.md |
| A6 / B6 | `Proyecto:` / código + nombre del proyecto | Bases del NOG |
| A7 / B7 | `Código:` / código del renglón (ej. `Co 601.07.02.A`) | Bases del NOG |
| A8 / B8 | `Renglón:` / descripción larga del renglón | Bases del NOG |
| A9 / B9 | `Unidad:` / unidad de medida | Bases del NOG |
| A10 / B10 | `Fecha:` / fecha de elaboración | Día de generación |

### Rendimiento (fila 12)

| Celda | Contenido | Notas |
|---|---|---|
| A12 / B12 / C12 | `Rendimiento:` / `{N}` / unidades/día | Catálogo por código de renglón |

**Crítico:** el rendimiento divide el costo total por jornada para obtener el precio unitario. Errores aquí inflan o reducen el P.U. drásticamente.

### Bloque EQUIPO (filas 14-20)

| Fila | A | B | F | G | H |
|---|---|---|---|---|---|
| 14 | `EQUIPO` (título) | | | | |
| 15 | `Cantidad` | `Descripción` | `Hrs.` | `Costo Hora` | `Sub-Total` |
| 16-19 | número | desc. equipo | 8 (típico) | Q/hora | `=A{fila}*F{fila}*G{fila}` |
| 20 | | | | `TOTAL EQUIPO` | `=SUM(H16:H19)` |

Equipo varía por tipo de obra. Para señalización: máquina termoplástica, caldera premelting, pickup, compresor.

### Bloque MANO DE OBRA (filas 22-28)

Misma estructura que EQUIPO. Para señalización típicamente: encargado, operador, ayudantes/banderilleros, conductor.

| Fila | A | B | F | G | H |
|---|---|---|---|---|---|
| 22 | `MANO DE OBRA` (título) | | | | |
| 23 | `Cantidad` | `Descripción` | `Hrs.` | `Costo Hora` | `Sub-Total` |
| 24-27 | número | descripción | 8 (típico) | Q/hora | `=A{fila}*F{fila}*G{fila}` |
| 28 | | | | `TOTAL M.O.` | `=SUM(H24:H27)` |

### Herramienta (fila 30)

| Celda | Contenido |
|---|---|
| A30 | `HERRAMIENTA (5% MANO DE OBRA)` |
| H30 | `=0.05*H28` |

Constante 5% sobre el total de MO.

### Bloque MATERIALES (filas 32-38)

| Fila | A | B | F | G | H |
|---|---|---|---|---|---|
| 32 | `MATERIALES` (título) | | | | |
| 33 | `Cantidad` | `Descripción` | `P.U.` | `Unidad` | `Sub-Total` |
| 34-37 | número | descripción | Q | unidad | `=A{fila}*F{fila}` |
| 38 | | | | `TOTAL MAT.` | `=SUM(H34:H37)` |

### Cálculo final (filas 40-47)

| Fila | D (etiqueta) | H (fórmula) |
|---|---|---|
| 40 | `Total Costo Directo:` | `=H28+H30+H38` |
| 41 | `Costos Indirectos (25%):` | `=0.25*H40` |
| 42 | `Equipo:` | `=H20` |
| 43 | `Subtotal (sin IVA):` | `=H40+H41+H42` |
| 44 | `IVA (12%):` | `=0.12*H43` |
| 45 | `Total por jornada (con IVA):` | `=H43+H44` |
| 47 | `PRECIO UNITARIO POR:` (F47) / `{unidad}` (G47) | `=H45/B12` |

> El **PRECIO UNITARIO (H47)** que se calcula aquí es exactamente el que va a la celda E correspondiente del cuadro ANEXO 8 (columna PRECIO UNITARIO).

---

## Constantes del formato (no cambian por oferta)

| Constante | Valor | Donde se usa |
|---|---|---|
| Costos indirectos | 25% del Costo Directo | Cada hoja de renglón, fila 41 |
| IVA | 12% | Cada hoja de renglón (fila 44) y ANEXO 8 |
| Herramienta | 5% de MO | Cada hoja de renglón, fila 30 |
| Horas/jornada | 8 hrs | Equipo y MO (col F) — convención COVIAL |

---

## Inputs que el generador necesita por oferta

Para generar una oferta nueva, `tools/generar_oferta.py --nog NNNN` (pendiente) necesita:

1. **Del NOG (de `data/guatecompras_local.db`, ya extraído):**
   - Código y nombre del proyecto
   - Unidad ejecutora (UECV/DGC/FSS/municipalidad)
   - Lista de renglones con cantidad y unidad
   - Plazo de ejecución
   - Ubicaciones / departamentos

2. **Del OFERENTE (input runtime — Rodrigo lo provee en el mensaje):**
   - Razón social, NIT, dirección, teléfonos, correo
   - Representante legal
   - Superintendente con colegiado y teléfono

3. **Del catálogo de renglones (`data/catalogo_renglones.json`):**
   - **Estado actual:** catálogo derivado de la oferta histórica OYL `Oferta_SG-002-2026_OYL.xlsx`. Tiene 32 renglones de **señalización** (Co 601.07.x, Co 602.x, Co 604).
   - **Pendiente:** catálogo oficial del cliente con todos los renglones de obra vial (pavimento rígido, subrasante, base granular, cunetas, drenajes, muros, etc.). Cuando llegue, se ubicará en `referencias/catalogo_renglones_covial.json` y tendrá prioridad sobre el derivado.
   - **Para renglones no encontrados en el catálogo:** Claudio los incluye en la ANEXO 8 con el código y descripción de las bases, pero deja `[FALTA AGREGAR]` en el precio unitario y omite la hoja de integración, listándolos al final para que Rodrigo los complete.

4. **Constantes globales (este documento):**
   - 25% indirectos, 12% IVA, 5% herramienta, 8 hrs/jornada

## Catálogo de renglones

El generador `tools/generar_oferta.py` carga el catálogo desde:
1. `referencias/catalogo_renglones_covial.json` — catálogo oficial del cliente (cuando exista, prevalece).
2. `data/catalogo_renglones.json` — catálogo unificado del workspace, 56 renglones de obra vial.

**Match semántico:** cada renglón del catálogo lleva un campo `aliases` con descripciones equivalentes. El generador busca primero por código COVIAL (regex `Co XXX.XX.XX` en la descripción del renglón del NOG), y como fallback hace match por substring normalizado contra los aliases. Esto le permite emparejar el renglón "Escarificación, conformación y compactación de subrasante" del NOG con el código `Co 304.01` del catálogo.

**Marcado visual en el .xlsx:**

| Color de fondo | Significado |
|---|---|
| Rojo claro | `[FALTA AGREGAR]` — no se encontró match en el catálogo |
| Amarillo | Totales de la oferta |
| Azul claro | Encabezados de tabla |

Cuando el cliente envíe el catálogo oficial completo, lo pones en `referencias/catalogo_renglones_covial.json` y el generador automáticamente lo prioriza.

---

## Cumplimiento legal (Decreto 57-92)

Esta plantilla cumple con:

- **Art. 6 LCE** (Precios unitarios y totales): la ANEXO 8 contiene el precio unitario de cada renglón expresado en quetzales, y cada hoja de integración respalda el cálculo.
- **Art. 19 num. 11 LCE** (Forma de integración de precios unitarios por renglón): las 32 hojas de integración son evidencia auditada del cálculo.
- **Art. 19 num. 14 LCE** (Modelo de oferta): la ANEXO 8 es el modelo de oferta que UECV publicó en las bases.

Lo que aún debe agregarse al expediente físico/digital de la oferta (no en este .xlsx):

- Carta de presentación de oferta firmada por representante legal
- Declaración jurada del Art. 26 (no estar en Art. 80 prohibiciones)
- Fianza de sostenimiento de oferta (Art. 64) — 1-5%
- Constancia de inscripción RGAE vigente (Art. 76)
- Solvencia fiscal SAT y constancia IGSS (Art. 80 lit. f y g)
- Acreditación de capacidad financiera mínima
- Solvencia municipal
- Documentación del superintendente (colegiado activo)
- Experiencia empresarial (finiquitos de obras anteriores)

Estos documentos los proporciona Rodrigo o se generan por separado; el .xlsx es solo la propuesta económica.
