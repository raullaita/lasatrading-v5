# Tarea 2: Implementación de la Importación de Datos

## 1. Objetivo
Implementar el módulo completo de importación de datos desde la API pública de Binance, incluyendo backend (API, servicio, tareas en segundo plano, modelos de base de datos) y frontend (pantallas de lista, wizard de configuración, progreso en tiempo real y resultado final). Al finalizar, el usuario podrá importar datos históricos OHLCV de forma transparente, validable y con trazabilidad completa.

## 2. Criterios de Aceptación
- El usuario puede ver una lista de todas las importaciones realizadas con su estado.
- El usuario puede crear una nueva importación mediante un wizard de 5 pasos.
- El selector de símbolos carga dinámicamente desde la API de Binance y permite búsqueda y filtrado.
- El usuario puede seleccionar múltiples símbolos y múltiples timeframes.
- El usuario puede configurar un rango de fechas con presets rápidos y selección personalizada.
- El usuario puede elegir el modo de importación (merge por defecto, append, overwrite).
- La importación se ejecuta en segundo plano sin bloquear la interfaz.
- El usuario ve el progreso en tiempo real con barra de progreso y log en vivo.
- El usuario puede cancelar una importación en curso.
- Los datos se almacenan en PostgreSQL con estrategia merge (actualizar existentes, insertar nuevos).
- Se calculan y muestran estadísticas finales de calidad, gaps y volúmenes procesados.
- El manejo de errores es robusto: una combinación fallida no detiene el resto.

## 3. Fuente de Datos: Binance API Pública
- Endpoint de velas (klines): GET /api/v3/klines con parámetros symbol, interval, startTime, endTime y limit (máximo 1000 por llamada).
- Endpoint de símbolos: GET /api/v3/exchangeInfo para obtener la lista completa de pares disponibles.
- No requiere API key para datos públicos.
- Rate limit: 1200 requests por minuto por IP.
- La respuesta de klines es un array de arrays donde cada elemento contiene: open time, open, high, low, close, volume, close time, quote asset volume, number of trades, taker buy base volume, taker buy quote volume, ignore.

## 4. Arquitectura del Módulo

### Backend
El módulo de importación reside en backend/app/modules/data_import/ y se compone de:
- **Modelos de base de datos:** Definición de las tablas import_jobs, import_job_combinations, import_logs y candles.
- **Cliente Binance:** Clase encargada de interactuar con la API de Binance, incluyendo caché de símbolos en Redis con TTL de 24 horas, manejo de rate limits con throttle de 100ms entre requests, y reintentos con backoff exponencial ante errores 429 y 5xx.
- **Servicio de importación:** Lógica de negocio que orquesta la creación de jobs, el procesamiento de combinaciones (symbol + timeframe), la descarga por chunks de 1000 velas, la inserción/actualización en base de datos con estrategia merge, el cálculo de estadísticas y la gestión de cancelaciones.
- **Tareas Celery:** Task de background que ejecuta el servicio de importación de forma asíncrona, actualizando el progreso en base de datos en tiempo real.
- **Router de API:** Endpoints REST y WebSocket para interactuar con el módulo desde el frontend.
- **Esquemas de validación:** Modelos Pydantic para validar la entrada y salida de los endpoints.

### Frontend
El módulo de importación reside en frontend/src/pages/DataImport/ y se compone de:
- **Pantalla de lista:** Tabla con todas las importaciones, filtros y botón para crear nueva.
- **Wizard de nueva importación:** Flujo guiado de 5 pasos (símbolos, timeframes, fechas, opciones, resumen).
- **Pantalla de detalle:** Vista dual que muestra progreso en tiempo real o resultado final según el estado del job.
- **Componentes reutilizables:** Selector de símbolos, selector de timeframes, selector de rango de fechas, barra de progreso, visor de logs y panel de estadísticas.

## 5. Modelos de Base de Datos

### Tabla import_jobs
Almacena los metadatos de cada importación. Campos: id (UUID, PK), status (pending/processing/completed/failed/cancelled), source_type (binance_api), started_at, finished_at, symbols (JSONB con array de strings), timeframes (JSONB con array de strings), date_from, date_to, import_mode (merge/append/overwrite), total_combinations, completed_combinations, failed_combinations, total_candles_downloaded, total_candles_inserted, total_candles_updated, error_summary (JSONB), created_at, updated_at.

### Tabla import_job_combinations
Almacena el estado de cada combinación symbol+timeframe dentro de un job. Campos: id (UUID, PK), job_id (FK a import_jobs), symbol, timeframe, status (pending/processing/completed/failed/cancelled), started_at, finished_at, candles_downloaded, candles_inserted, candles_updated, first_candle_at, last_candle_at, error_message. Restricción de unicidad en (job_id, symbol, timeframe).

### Tabla import_logs
Almacena los logs de cada job para trazabilidad y visualización en tiempo real. Campos: id (UUID, PK), job_id (FK a import_jobs), combination_id (FK opcional a import_job_combinations), timestamp, level (info/warning/error), message, progress (entero 0-100 opcional). Índice en (job_id, timestamp).

### Tabla candles
Almacena los datos OHLCV normalizados. Campos: timestamp, symbol, timeframe, open, high, low, close, volume, import_job_id (FK a import_jobs). Los campos open, high, low, close y volume usan tipo NUMERIC(20,8) (DECIMAL(20,8)); nunca FLOAT. Clave primaria compuesta: (timestamp, symbol, timeframe). Índices en (symbol, timeframe, timestamp DESC) para consultas eficientes por rango. La tabla se convierte en hipertabla de TimescaleDB mediante `SELECT create_hypertable('candles', 'timestamp')`.

## 6. Estrategia de Merge (Opción C)
La estrategia de merge es el modo por defecto y funciona así:
- Si la vela no existe en la tabla candles: INSERT.
- Si la vela existe y es idéntica: SKIP (no hacer nada).
- Si la vela existe y es diferente: UPDATE con los nuevos valores.
- Se implementa mediante INSERT ... ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET ... WHERE los valores son diferentes.
- Se actualiza el campo import_job_id para mantener trazabilidad de la última importación que tocó cada vela.

### Validación de calidad de velas
Antes de insertar cada vela se aplican los siguientes checks; si alguno falla, la vela se descarta y el error se registra en error_summary del job:
- `high >= MAX(open, close)`
- `low <= MIN(open, close)`
- `high >= low`
- `volume >= 0`

## 7. Endpoints de la API

### REST
- POST /api/v1/data-import/start: Recibe la configuración (símbolos, timeframes, rango de fechas, modo), crea el job en BD, lanza la tarea Celery y retorna el job_id.
- GET /api/v1/data-import/list: Retorna la lista de jobs con filtros opcionales por estado, símbolo y paginación.
- GET /api/v1/data-import/status/{job_id}: Retorna el estado actual del job con estadísticas parciales o finales.
- GET /api/v1/data-import/symbols: Retorna la lista de símbolos disponibles en Binance (con caché Redis de 24h).
- GET /api/v1/data-import/preview/{job_id}: Retorna una muestra de los datos importados (primeras y últimas N filas) con filtros opcionales por símbolo y timeframe.
- GET /api/v1/data-import/stats/{job_id}: Retorna estadísticas detalladas de la importación (calidad, gaps, volúmenes).
- POST /api/v1/data-import/cancel/{job_id}: Cancela un job en curso, marcando combinaciones pendientes como canceladas.

### WebSocket
- WS /api/v1/data-import/logs/{job_id}: Conexión WebSocket que envía logs en tiempo real al frontend. El backend hace polling a la tabla import_logs y envía los nuevos registros al cliente. Se cierra cuando el job termina.

## 8. Flujo de Ejecución de una Importación
1. El usuario completa el wizard y pulsa "Iniciar importación".
2. El frontend envía la configuración al endpoint POST /start.
3. El backend crea un registro en import_jobs con estado "pending".
4. El backend crea un registro en import_job_combinations por cada par symbol+timeframe.
5. El backend lanza una tarea Celery en background.
6. La tarea Celery marca el job como "processing".
7. Para cada combinación (secuencialmente, con throttle de 100ms):
   a. Marca la combinación como "processing".
   b. Calcula el rango de timestamps y divide en chunks de 1000 velas.
   c. Antes de procesar cada chunk, consulta el estado del job en BD; si es "cancelled", aborta limpiamente la tarea sin procesar más chunks.
   d. Para cada chunk: descarga de Binance, parsea, inserta/actualiza en BD (merge), escribe log, actualiza progreso.
   e. Si falla: marca la combinación como "failed" con el error, continúa con la siguiente.
   f. Si tiene éxito: marca la combinación como "completed" con estadísticas.
8. Al terminar todas las combinaciones: calcula estadísticas finales, marca el job como "completed" o "failed" (si todas fallaron).
9. El frontend, que está conectado por WebSocket y haciendo polling de estado, muestra el resultado final.

## 9. Wizard de Nueva Importación (5 Pasos)

### Paso 1: Selector de Símbolos
- Carga la lista de símbolos desde GET /api/v1/data-import/symbols.
- Lista scrolleable con checkboxes para selección múltiple.
- Campo de búsqueda en tiempo real con debounce.
- Filtros rápidos: solo pares USDT, solo estado TRADING.
- Contador de símbolos seleccionados.
- Botones para seleccionar/deseleccionar todos.
- Validación: mínimo 1 símbolo seleccionado para avanzar.

### Paso 2: Selector de Timeframes
- Timeframes agrupados en tres categorías: Intradía (1m, 3m, 5m, 15m, 30m), Swing (1h, 2h, 4h, 6h, 8h, 12h), Posicional (1d, 3d, 1w, 1M).
- Checkboxes para selección múltiple.
- Por defecto seleccionados: 1h, 4h, 1d.
- Validación: mínimo 1 timeframe seleccionado para avanzar.

### Paso 3: Rango de Fechas
- Presets rápidos: último mes, últimos 3 meses, último año, últimos 2 años.
- Selectores de fecha para rango personalizado.
- Por defecto: último año.
- Validación: fecha inicio anterior a fecha fin.

### Paso 4: Opciones de Importación
- Tres modos con radio buttons: Merge (recomendado, por defecto), Append, Overwrite.
- Explicación clara de cada modo:
  - **Append:** `INSERT ... ON CONFLICT DO NOTHING` (solo añade velas nuevas, no actualiza las existentes).
  - **Overwrite:** `DELETE` del rango de fechas seleccionado antes de insertar.
- Advertencia visual para el modo Overwrite.

### Paso 5: Resumen y Lanzamiento
- Resumen completo: símbolos seleccionados, timeframes, total de combinaciones, rango de fechas, modo.
- Estimación de tiempo calculada: total de velas / 1000 = número de requests, multiplicado por 0.1 segundos por request (throttle de 100ms) más la latencia estimada de la llamada.
- Nota informativa: la importación continuará en background aunque se cierre la pestaña.
- Botón "Iniciar importación" que envía la configuración al backend y navega a la pantalla de detalle.

## 10. Pantalla de Progreso (durante la importación)
- Barra de progreso general con porcentaje y texto "Combinación X de Y".
- Detalle de la combinación actual: símbolo, timeframe, progreso individual.
- Contadores de estado: completadas, en curso, pendientes.
- Estadísticas parciales en tiempo real: velas descargadas, insertadas, actualizadas, errores.
- Visor de logs en tiempo real conectado por WebSocket, con scroll automático y colores por nivel (info, warning, error).
- Botón "Cancelar" con confirmación previa.
- Polling cada 2 segundos para actualizar progreso general.

## 11. Pantalla de Resultado (al finalizar)
- Estado final con icono y color: completada (verde), fallida (rojo), cancelada (gris).
- Duración total de la importación.
- Resumen: combinaciones procesadas, exitosas vs fallidas.
- Estadísticas de datos: velas descargadas, insertadas, actualizadas, omitidas.
- Lista de incidencias: errores y warnings con mensajes claros.
- Tabla detallada de cada combinación: símbolo, timeframe, estado, velas procesadas, rango de fechas.
- Botones de acción: "Ver datos" (navega a preview), "Nueva importación" (navega al wizard), "Reintentar fallidas" (si hay combinaciones fallidas, crea un nuevo job solo con esas).

## 12. Pantalla de Lista de Importaciones
- Tabla con columnas: Símbolo(s), Timeframe(s), Estado, Filas procesadas, Fecha, Acciones.
- Estados visuales con colores e iconos: completada (verde), en curso (azul con animación), fallida (rojo), cancelada (gris).
- Filtros por estado, símbolo y fecha.
- Ordenación por columnas.
- Botón "Nueva importación" en la cabecera.
- Click en una fila navega a la pantalla de detalle de ese job.

## 13. Manejo de Errores

### Errores de la API de Binance
- Error 400 (símbolo no existe): marcar la combinación como fallida, continuar con las demás.
- Error 429 (rate limit): esperar 60 segundos y reintentar, máximo 3 reintentos.
- Error 5xx (servidor): reintentar 3 veces con backoff exponencial.
- Timeout de red: reintentar 3 veces con backoff exponencial.

### Errores de Base de Datos
- Violación de constraint: log del error, continuar con la siguiente vela.
- Pérdida de conexión: reintentar conexión antes de abortar la combinación.

### Errores de Frontend
- Error de red en llamadas API: mostrar mensaje claro con botón "Reintentar".
- Error de validación en el wizard: mostrar en el campo correspondiente, bloquear avance.
- Desconexión de WebSocket: reconectar automáticamente, si no es posible, cambiar a polling.

## 14. Consideraciones de Rendimiento
- Descarga secuencial de combinaciones (no paralela) para respetar rate limits de Binance.
- Throttle de 100ms entre requests a la API.
- Procesamiento por chunks de 1000 velas tanto en descarga como en inserción.
- Inserción en BD mediante bulk operations con INSERT ... ON CONFLICT.
- Transacciones por chunk (no una transacción gigante para todo el job).
- Escritura de logs en BD agrupada (no un INSERT por cada línea de log).
- Frontend: lista de símbolos virtualizada si supera los 1000 elementos, búsqueda con debounce de 300ms, visor de logs con máximo 500 líneas en pantalla.

## 15. Migraciones de Base de Datos
- Se deben crear las 4 tablas (import_jobs, import_job_combinations, import_logs, candles) mediante una migración de Alembic.
- Se deben crear los índices especificados en la sección de modelos.
- La migración debe ser reversible (downgrade debe eliminar las tablas).

## 16. Criterios de Finalización
La tarea se considera completada cuando:
1. El usuario puede ver la lista de importaciones (vacía inicialmente).
2. El usuario puede completar el wizard de 5 pasos y lanzar una importación real contra la API de Binance.
3. El selector de símbolos carga dinámicamente desde Binance y la búsqueda funciona.
4. La importación se ejecuta en background y no bloquea la interfaz.
5. El progreso se actualiza en tiempo real con barra y logs vía WebSocket.
6. El usuario puede cancelar una importación en curso y el sistema limpia correctamente.
7. Los datos se almacenan en PostgreSQL y la estrategia merge funciona correctamente (segunda importación actualiza, no duplica).
8. Las estadísticas finales se calculan y muestran correctamente.
9. Una combinación fallida no detiene el resto del job.
10. La pantalla de resultado muestra toda la información incluyendo incidencias.
11. El botón "Reintentar fallidas" funciona correctamente.
12. La migración de base de datos se aplica correctamente con alembic upgrade head.

## 17. Dependencias de esta Tarea
- Depende de: Tarea 1 (Inicialización del proyecto).
- Bloquea: Tarea 3 (Cálculo de Features/Indicadores).
- Estimación: 5-7 días de trabajo.

## 18. Restricciones
- Solo se implementa Binance como fuente de datos en esta tarea, pero la arquitectura del cliente debe permitir añadir más fuentes en el futuro sin refactorizar el servicio de importación.
- No implementar automatización de importaciones periódicas (se hará en tareas posteriores).
- No implementar detección de gaps como funcionalidad separada, solo como estadística informativa en el resultado.
- El modo merge es el único que se implementa completamente; append y overwrite pueden quedar como placeholders funcionales.