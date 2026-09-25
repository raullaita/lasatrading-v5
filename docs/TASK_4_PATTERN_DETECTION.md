Tarea 4: Motor de Detección de Patrones de Trading
1. Objetivo
Implementar un motor de escaneo (scanner) que analice los datos históricos de velas (candles) y los indicadores calculados (features) para identificar automáticamente patrones de trading clásicos. El sistema permitirá al usuario configurar escaneos asíncronos sobre rangos de fechas específicos y visualizar los resultados (ocurrencias) tanto en tablas como directamente sobre el gráfico de velas mediante marcadores visuales.
2. Criterios de Aceptación
2.1. Funcionalidad
El usuario puede crear un "Scan Job" seleccionando símbolo, timeframe, rango de fechas y los patrones específicos que desea buscar.
El escaneo se ejecuta en segundo plano (Celery) para no bloquear la interfaz, con progreso en tiempo real vía WebSocket.
Los resultados se almacenan como "Ocurrencias" (Pattern Occurrences) vinculadas a un timestamp exacto.
El usuario puede ver una lista de todas las ocurrencias detectadas, filtrables por patrón, símbolo y fecha.
El usuario puede hacer clic en una ocurrencia y ver el gráfico de velas con un marcador visual (icono/flecha) exactamente en la vela donde se disparó el patrón.
2.2. Técnico
El motor de escaneo utiliza operaciones vectorizadas de pandas/numpy (evitando bucles "for" fila por fila) para garantizar rendimiento sobre millones de velas.
Los resultados se almacenan en una nueva hipertabla de TimescaleDB (pattern_occurrences).
Se reutiliza la arquitectura de Jobs (creación, cancelación, logs, borrado) de las Tareas 2 y 3.
Integración nativa con lightweight-charts usando la API de markers para señalizar eventos en el gráfico.
3. Patrones a Implementar en V1
El sistema incluirá un catálogo inicial de 5 patrones fundamentales que combinan precio y features:
Cruce de MACD (MACD Crossover)
Lógica: La línea MACD cruza por encima (alcista) o por debajo (bajista) de la línea de Señal.
Dependencias: features MACD_12_26_9 y MACDs_12_26_9.
RSI Extremo (RSI Overbought/Oversold)
Lógica: El RSI cruza hacia arriba desde abajo de 30 (salida de sobreventa) o cruza hacia abajo desde arriba de 70 (salida de sobrecompra).
Dependencias: feature RSI_14.
Ruptura de Bandas de Bollinger (Bollinger Breakout)
Lógica: El precio de cierre (close) rompe y cierra por encima de la Banda Superior o por debajo de la Banda Inferior.
Dependencias: Candle.close y features BBU_20_2.0, BBL_20_2.0.
Cruce de Medias Móviles (Moving Average Crossover)
Lógica: Una EMA rápida (ej. EMA_20) cruza una EMA lenta (ej. EMA_50).
Dependencias: features EMA_20 y EMA_50.
Vela Envolvente (Engulfing Candle)
Lógica: Patrón puro de precio. El cuerpo de la vela actual envuelve completamente el cuerpo de la vela anterior, con cambio de dirección (alcista o bajista).
Dependencias: Solo Candle (open, close, prev_open, prev_close).
4. Arquitectura
4.1. Backend: Modelos de Base de Datos
Tabla pattern_scan_jobs (Similar a feature_jobs)
id (UUID, PK)
status (pending, processing, completed, failed, cancelled)
symbol, timeframe, date_from, date_to
patterns_config (JSONB): Lista de patrones a buscar y sus parámetros (ej. umbrales de RSI).
total_candles, processed_candles, started_at, finished_at, error_message.
Relaciones: logs (cascade delete), occurrences (cascade delete).
Tabla pattern_occurrences (Hipertabla TimescaleDB)
timestamp (datetime, PK)
symbol (str, PK)
timeframe (str, PK)
pattern_name (str, PK) (ej: "MACD_CROSS_BULLISH", "RSI_OVERBOUGHT_EXIT")
scan_job_id (UUID, FK a pattern_scan_jobs, ondelete=CASCADE)
metadata (JSONB): Datos contextuales (ej: {"rsi_value": 68.5, "threshold": 70, "direction": "bearish"}).
PK compuesta: (timestamp, symbol, timeframe, pattern_name)
Tabla pattern_definitions (Catálogo estático o en memoria)
No requiere tabla en BD para V1. Se define como un diccionario/clase en Python (pattern_catalog.py) con el nombre, descripción, lógica de cálculo y parámetros configurables de cada patrón.
4.2. Backend: Motor de Escaneo (Scanner)
Archivo: backend/app/modules/patterns/scanner.py
Clase PatternScanner con métodos vectorizados:
scan_macd_crossover(df): Compara MACD y Signal desplazados (shift) para detectar cruces.
scan_rsi_extremes(df, threshold_up=70, threshold_down=30): Detecta cruces de umbrales.
scan_bollinger_breakout(df): Compara close con bandas superiores/inferiores.
scan_ma_crossover(df, fast_col, slow_col): Detecta cruces de medias.
scan_engulfing(df): Compara open/close actuales con open/close anteriores (shift).
El método principal execute_scan(job_id) carga las velas y las features en un solo DataFrame (merge por timestamp), ejecuta los scanners seleccionados, concatena los resultados y los inserta en pattern_occurrences usando la estrategia de lotes (batch insert).
4.3. Backend: API y Endpoints
Archivo: backend/app/modules/patterns/router.py
POST /api/v1/patterns/scans (Crear y lanzar scan job)
GET /api/v1/patterns/scans (Listar jobs con filtros)
GET /api/v1/patterns/scans/{job_id} (Detalle del job)
DELETE /api/v1/patterns/scans/{job_id} (Borrar job y ocurrencias)
DELETE /api/v1/patterns/scans/batch (Borrado múltiple)
GET /api/v1/patterns/occurrences (Listar ocurrencias globales o filtradas por job/símbolo/patrón)
GET /api/v1/patterns/catalog (Devuelve el catálogo de patrones disponibles para el UI)
WebSocket /api/v1/patterns/scans/{job_id}/logs (Logs en tiempo real)
4.4. Frontend: UI y Gráficos
Páginas:
/patterns: Lista de Scan Jobs (con checkboxes, filtros, botones de acción).
/patterns/new: Wizard para configurar el scan (Seleccionar datos -> Seleccionar patrones a buscar -> Confirmar).
/patterns/occurrences: Tabla maestra de todos los patrones detectados en el sistema, agrupables por símbolo.
/patterns/scans/{jobId}: Detalle del job con tabla de ocurrencias específicas.
Componentes Clave:
PatternSelector: Checkboxes o lista multi-selección con los patrones del catálogo y sus parámetros (ej. slider para umbral de RSI).
PatternChart: Extensión del FeatureChart. Además de las velas y las líneas de indicadores, recibe un array de occurrences y utiliza la API setMarkers() de lightweight-charts para dibujar flechas (▲ verde para alcista, ▼ rojo para bajista) en las velas correspondientes. Al hacer hover sobre el marcador, muestra un tooltip con la metadata del patrón.
5. Flujo de Trabajo del Usuario
El usuario va a "Nuevo Escaneo" (/patterns/new).
Selecciona BTCUSDT, 1h, último año.
Selecciona los patrones: "Cruce de MACD" y "RSI Extremo". Configura el umbral de RSI a 75/25.
Lanza el escaneo. El backend valida que existan velas y features (si no existen features, sugiere ir a la Tarea 3 o las calcula al vuelo si el motor lo soporta, aunque para V1 exigiremos que las features estén precalculadas).
El job procesa el DataFrame vectorizado.
Al terminar, el usuario ve una lista de 42 ocurrencias (ej. 15 cruces MACD, 27 eventos RSI).
El usuario hace clic en una ocurrencia. Se abre el gráfico centrado en esa fecha, mostrando la vela, las líneas de indicadores y el marcador exacto donde se cumplió la condición.
6. Consideraciones Técnicas Críticas
6.1. Rendimiento (Vectorización)
El motor de escaneo NUNCA debe usar iterrows() o bucles for sobre el DataFrame. Todas las detecciones deben hacerse usando operaciones de pandas como shift(), where(), y comparaciones booleanas (ej. cruce = (macd_prev < signal_prev) & (macd_curr > signal_curr)). Esto permite escanear 1 millón de velas en milisegundos.
6.2. Dependencia de Features
Para V1, el motor de patrones asumirá que las features necesarias ya fueron calculadas (Tarea 3). Si el usuario intenta buscar "Cruce de MACD" pero no hay datos en la tabla features para ese rango, el job fallará con un error claro: "Faltan features: MACD_12_26_9. Por favor, ejecuta un cálculo de indicadores primero."
6.3. Marcadores en lightweight-charts
La librería soporta markers con la estructura:
{ time: unix_timestamp, position: 'aboveBar', color: '#219653', shape: 'arrowUp', text: 'MACD Bull' }
El frontend debe mapear nuestras occurrences a este formato y aplicarlos a la serie de velas (candlestickSeries.setMarkers(markers)).
6.4. Convención de Nombres
Los pattern_name deben ser descriptivos y únicos. Ejemplos:
MACD_CROSS_BULLISH, MACD_CROSS_BEARISH
RSI_EXIT_OVERBOUGHT, RSI_EXIT_OVERSOLD
BB_BREAKOUT_UPPER, BB_BREAKOUT_LOWER
ENGULFING_BULLISH, ENGULFING_BEARISH
7. Criterios de Finalización
Backend: Modelos, Scanner vectorizado, Router API y Tareas Celery implementados.
Frontend: Wizard de configuración, tabla de ocurrencias y gráfico con marcadores funcionales.
El sistema es capaz de escanear 100,000 velas en menos de 2 segundos.
Verificación end-to-end: Crear scan -> Detectar patrones conocidos en datos históricos -> Ver marcadores en el gráfico.
8. Estimación
Backend (Modelos + API + Celery): 2 días
Backend (Motor de Escaneo Vectorizado): 2 días
Frontend (UI + Integración de Markers en Gráficos): 3 días
Testing y optimización de rendimiento: 1 día
Total estimado: 8 días