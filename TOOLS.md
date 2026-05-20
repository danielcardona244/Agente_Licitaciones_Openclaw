# TOOLS.md - Herramientas de Datos Local

## Herramienta Core: Consultar Licitaciones de Construcción
- **Descripción:** Ejecuta una consulta directa en la base de datos local SQLite (`guatecompras_local.db`) sobre la tabla de concursos viales e infraestructura filtrados.
- **Comando de ejecución (shell):** `python consultar_db.py`
- **Filtro operativo por defecto:** proyectos de las entidades objetivo con `estado = vigente`, `fecha_publicacion >= 2026-05-01` y categoría OCDS `works` (ejecución de obra).
- **Fuente oficial:** `inicializar_db.py` alimenta la base desde la API OCDS real `https://ocds.guatecompras.gt/release/search` con `Estatus_concurso=1`.
- **Entidades objetivo:** Unidad Ejecutora de Conservación Vial, Dirección General de Caminos y Fondo Social de Solidaridad.
- **Exclusión operativa:** no reportar servicios, compras, mantenimiento de maquinaria, combustibles, señalización o suministros si no están clasificados como ejecución de obra (`mainProcurementCategory = works`).
- **Argumentos permitidos:**
  - `--limite X` (Donde X es el número de filas a traer, por defecto es 5)
  - `--desde YYYY-MM-DD` (Fecha mínima de publicación, por defecto `2026-05-01`)
  - `--estado ESTADO` (Estado del concurso, por defecto `vigente`)
  - `--solo-viales` (Aplica filtro adicional por palabras clave viales)
  - `--todos-los-sectores` (Compatibilidad: no aplica filtro vial)
  - `--todas-las-entidades` (Desactiva el filtro de entidades objetivo)
  - `--incluir-servicios` (Incluye servicios/compras; usar solo si Rodrigo lo pide expresamente)

### Instrucciones de Despliegue para Claudio:
Cuando Rodrigo solicite reportes, top de montos o listados de licitaciones:
1. Ejecuta inmediatamente el comando `python consultar_db.py --limite 5` en la terminal local (`shell`). Este comando ya trae solo proyectos vigentes publicados desde el 1 de mayo de 2026 en adelante, de las tres entidades objetivo y clasificados como ejecución de obra.
2. Lee el flujo JSON resultante.
3. Traduce la información a un reporte formal de ingeniería en Telegram. Resalta los NOGs en negrita, incluye estado, modalidad, fecha de publicación, fecha de cierre, monto en Quetzales (ej. Q2,800,000.00) y el link directo de consulta para que Rodrigo pueda darle clic desde su teléfono.

## Rutina Diaria: Carreteras por Unidad Compradora
- **Criterios persistentes:** ver `GUATECOMPRAS_CRITERIOS.md`.
- **Unidades objetivo diarias:**
  - Unidad Ejecutora de Conservación Vial
  - Compras DGC
  - Fondo Social de Solidaridad
- **Ranking solicitado:** conveniencia ordenada por volumen de obra, de mayor a menor.
- **Nota técnica:** si OCDS no trae cantidades físicas, revisar o señalar la necesidad de descargar bases/anexos para extraer m², ml, m³ y renglones de obra.
