Tarea 3: Implementación del Cálculo de Features e Indicadores
1. Objetivo
Implementar el módulo de cálculo de indicadores técnicos (features) sobre los datos OHLCV importados. Este módulo permitirá al usuario seleccionar datos existentes, configurar indicadores técnicos con sus parámetros, y calcularlos de forma asíncrona para su posterior uso en detección de patrones y backtesting.
2. Criterios de Aceptación
2.1. Funcionalidad
El usuario puede seleccionar un símbolo y timeframe existentes en la tabla candles
El usuario puede seleccionar un rango de fechas dentro de los datos disponibles
El usuario puede configurar uno o más indicadores técnicos con sus parámetros
El cálculo se ejecuta en segundo plano (Celery) sin bloquear la interfaz
El usuario puede ver el progreso del cálculo en tiempo real (WebSocket)
El usuario puede ver una vista previa de los datos calculados (tabla con columnas OHLCV + indicadores)
El usuario puede ver un gráfico de velas con los indicadores superpuestos
El usuario puede borrar jobs de cálculo (similar al módulo de importación)
2.2. Técnico
Los indicadores se calculan usando pandas-ta (librería Python pura, sin dependencias de C)
Los resultados se almacenan en una nueva tabla features (hipertabla TimescaleDB)
Cada cálculo genera un feature_job con trazabilidad completa
La estrategia de cálculo es "merge" (similar a importación): si el indicador ya existe con los mismos parámetros, se actualiza; si no, se inserta
Los indicadores soportados en V1: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Volume SMA
2.3. Calidad
Tests unitarios para la lógica de cálculo de indicadores
Tests de integración para el flujo completo (API → Celery → BD)
Validación de calidad de datos (no generar NaNs, verificar continuidad temporal)
3. Arquitectura
3.1. Backend
3.1.1. Modelos (SQLAlchemy)
Tabla feature_jobs (similar a import_jobs):
id: UUID (PK)
status: str (pending, processing, completed, failed, cancelled)
symbol: str
timeframe: str
date_from: datetime
date_to: datetime
indicators_config: JSONB (lista de indicadores con sus parámetros)
started_at: datetime (nullable)
finished_at: datetime (nullable)
total_candles: int
processed_candles: int
error_message: str (nullable)
created_at: datetime
updated_at: datetime
logs: relationship con FeatureLog (cascade all, delete-orphan)
Tabla feature_logs (similar a import_logs):
id: UUID (PK)
job_id: UUID (FK → feature_jobs.id, ondelete=CASCADE)
timestamp: datetime
level: str (info, warning, error)
message: str
progress: int (nullable, porcentaje 0-100)
job: relationship con FeatureJob
Tabla features (hipertabla TimescaleDB):
timestamp: datetime (PK)
symbol: str (PK)
timeframe: str (PK)
indicator_name: str (PK) (ej: "SMA_20", "RSI_14", "MACD_12_26_9")
indicator_params: JSONB (ej: {"period": 20} o {"fast": 12, "slow": 26, "signal": 9})
value: Numeric(20, 8)
feature_job_id: UUID (FK → feature_jobs.id, ondelete=SET NULL)
PK compuesta: (timestamp, symbol, timeframe, indicator_name)
Nota sobre el diseño de features: Usamos un formato "largo" (una fila por indicador por timestamp) en lugar de "ancho" (una columna por indicador). Ventaja: flexible, permite añadir indicadores sin migraciones. Desventaja: más filas, pero TimescaleDB maneja esto eficientemente.
3.1.2. Servicio de Cálculo
Archivo: backend/app/modules/features/service.py
Clase FeatureService con métodos:
create_job(config): Valida que existan datos en candles, crea feature_job con status=pending
execute_job(job_id): Carga datos de candles en DataFrame, calcula indicadores, guarda en features, actualiza progress
_calculate_indicator(df, indicator): Usa pandas-ta para calcular el indicador
_save_features(df, job, indicator): Inserta/actualiza en la tabla features (merge)
3.1.3. Tareas Celery
Archivo: backend/app/modules/features/tasks.py
Tarea run_feature_job que envuelve el servicio asíncrono con asyncio.run()
3.1.4. Router API
Archivo: backend/app/modules/features/router.py
Endpoints:
POST /api/v1/features/jobs → Crea un job de cálculo
GET /api/v1/features/jobs → Lista todos los jobs (con filtros: status, symbol, timeframe)
GET /api/v1/features/jobs/{job_id} → Detalle de un job
GET /api/v1/features/jobs/{job_id}/preview → Vista previa de los datos calculados
POST /api/v1/features/jobs/{job_id}/cancel → Cancela un job en proceso
DELETE /api/v1/features/jobs/{job_id} → Borra un job y sus logs
DELETE /api/v1/features/jobs/batch → Borrado múltiple
DELETE /api/v1/features/jobs/{job_id}/logs → Borra solo los logs
POST /api/v1/features/jobs/{job_id}/requeue → Reenvía un job pendiente a la cola
GET /api/v1/features/data/available → Lista símbolos y timeframes disponibles
WebSocket /api/v1/features/jobs/{job_id}/logs → Logs en tiempo real
3.1.5. Esquemas Pydantic
Archivo: backend/app/modules/features/schemas.py
Clases:
IndicatorConfig: name (str), params (dict)
FeatureJobConfig: symbol, timeframe, date_from, date_to, indicators (list[IndicatorConfig])
FeatureJobResponse: id, status, symbol, timeframe, date_from, date_to, indicators_config, total_candles, processed_candles, error_message, created_at, started_at, finished_at
FeaturePreviewRow: timestamp, open, high, low, close, volume, indicators (dict[str, Decimal])
3.2. Frontend
3.2.1. Estructura de Páginas
Rutas:
/features → Lista de jobs de cálculo
/features/new → Wizard para crear un nuevo job
/features/:jobId → Detalle de un job
Componentes principales:
FeatureList.tsx → Tabla de jobs con filtros, checkboxes, botones de acción
NewFeatureJob.tsx → Wizard de 4 pasos: selección de datos, configuración de indicadores, resumen, confirmación
FeatureDetail.tsx → Vista de progreso en tiempo real + preview + gráfico
IndicatorSelector.tsx → Componente para seleccionar y configurar indicadores
FeatureChart.tsx → Gráfico de velas con indicadores superpuestos
3.2.2. Servicios API
Archivo: frontend/src/services/featuresApi.ts
Funciones:
createFeatureJob(config)
getFeatureJobs(filters)
getFeatureJob(jobId)
getFeatureJobPreview(jobId)
cancelFeatureJob(jobId)
deleteFeatureJob(jobId)
deleteFeatureJobsBatch(jobIds)
clearFeatureJobLogs(jobId)
requeueFeatureJob(jobId)
getAvailableData()
3.2.3. WebSocket
Archivo: frontend/src/services/featuresWebSocket.ts
Función connectFeatureJobLogs que retorna función de cleanup
3.3. Librería de Cálculo: pandas-ta
Justificación:
Librería Python pura, sin dependencias de C
130+ indicadores técnicos soportados
Integración nativa con pandas DataFrames
Mantenimiento activo y documentación clara
Indicadores a implementar en V1:
SMA (Simple Moving Average)
EMA (Exponential Moving Average)
RSI (Relative Strength Index)
MACD (Moving Average Convergence Divergence)
Bollinger Bands
ATR (Average True Range)
Volume SMA
Nota: MACD y Bollinger Bands generan múltiples columnas. Debemos guardar todas como indicadores separados.
4. Flujo de Trabajo del Usuario
Selección de datos: Usuario accede a /features/new, selecciona symbol, timeframe y rango de fechas
Configuración de indicadores: Usuario selecciona indicadores y configura parámetros
Resumen y confirmación: Sistema muestra configuración y estima tiempo de cálculo
Progreso en tiempo real: Usuario ve barra de progreso y logs en tiempo real
Visualización de resultados: Usuario ve tabla de preview y gráfico de velas con indicadores
Gestión de jobs: Desde /features, usuario puede cancelar, borrar, reenviar jobs
5. Consideraciones Técnicas
5.1. Estrategia de Cálculo: Merge
Similar a la importación de datos, usamos estrategia "merge": si el indicador ya existe, actualizar; si no, insertar.
5.2. Manejo de NaNs
pandas-ta puede generar NaNs en los primeros valores. Debemos detectar y reportar cuántos NaNs se generaron.
5.3. Rendimiento
Para V1, asumimos rangos de hasta 2 años. Si el rendimiento es un problema, considerar procesamiento por chunks.
5.4. Validación de Datos
Antes de calcular indicadores, validar que existan datos, que estén completos y que los valores sean válidos.
6. Dependencias
6.1. Backend
pandas-ta (nueva dependencia en requirements.txt)
pandas (dependencia de pandas-ta)
6.2. Frontend
Librería de gráficos: lightweight-charts (TradingView) o recharts
Recomendación: lightweight-charts para V1
7. Criterios de Finalización
Backend: modelos, servicio, tareas Celery, router API completos
Frontend: lista, wizard, detalle, gráfico completos
Tests unitarios para cálculo de indicadores
Tests de integración para flujo completo
Documentación actualizada
Verificación end-to-end: crear job → calcular → ver preview → ver gráfico → borrar job
8. Estimación
Backend: 3-4 días
Frontend: 3-4 días
Tests y documentación: 1-2 días
Total: 7-10 días
9. Notas Adicionales
Esta tarea es independiente de la Tarea 4 (Detección de Patrones), pero la habilita
Los indicadores calculados podrán ser usados como "features" para entrenar modelos de ML (futuro)
El gráfico de velas con indicadores es una funcionalidad clave para la validación visual