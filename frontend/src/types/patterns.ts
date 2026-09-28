import type { ChartData } from "./chart";

/**
 * Tipos del modulo de patrones, espejo de `backend/app/modules/patterns/schemas.py`.
 *
 * Convención: los nombres de campo van en snake_case porque es lo que FastAPI
 * serializa. No se traducen a camelCase en la capa de tipos; si algún día se
 * quiere, el sitio es un mapper, no los componentes.
 *
 * Todas las fechas son strings ISO 8601 en UTC. Se dejan como `string` y no
 * como `Date` a proposito: el backend las emite con microsegundos y zona, y
 * construir un `Date` obliga a decidir quien_local time zone, que en un
 * servidor de trading casi nunca es la del usuario. Quien necesite comparar
 * o formatear lo hace en el punto de uso.
 */

// ---------------------------------------------------------------------------
// Catalogo
// ---------------------------------------------------------------------------

/** `MACD_CROSS_BULLISH`, `RSI_EXIT_OVERSOLD`, ... Los 10 codigos del catalogo. */
export type PatternCode = string;

/** Familia de patrones. Los dos codigos de cada familia comparten scanner. */
export type PatternGroup =
  "macd_crossover" | "rsi_extremes" | "bollinger_breakout" | "ma_crossover" | "engulfing";

/**
 * Sentido del patron, ya resuelto en el catalogo.
 *
 * Ojo con `RSI_EXIT_*`: `RSI_EXIT_OVERSOLD` es `bullish` (saliendo de
 * sobreventa) y `RSI_EXIT_OVERBOUGHT` es `bearish`. El nombre del patron
 * describe el estado del que se sale, no la direccion a la que se entra.
 */
export type PatternDirection = "bullish" | "bearish";

/** Tipo de input que genera el selector de parametros. */
export type PatternParamKind = "int" | "float";

/**
 * `PatternParamSpecOut`. Un parametro configurable de un patron.
 *
 * `step` llega como `1` para kind `int` y como el incremento real para `float`;
 * el backend lo normaliza en `ParamSpec` para que el `<input type=number>` no
 * tenga que inventarse el incremento.
 */
export interface PatternParamSpec {
  key: string;
  label: string;
  kind: PatternParamKind;
  default: number;
  minimum: number;
  maximum: number;
  step: number;
  help: string;
}

/**
 * `PatternDefinitionOut`. Una entrada de `GET /catalog`.
 *
 * `required_features` es lo que decide si un par (simbolo, timeframe) puede
 * escanearse con este patron: los defaults de `MA_CROSS_*` piden `EMA_20` y
 * `EMA_50`, y si el par solo tiene `EMA_20` el POST /scans devuelve 400. El
 * frontend tiene que comparar esta lista contra los `indicators` de
 * `getAvailableData()` antes de dejar encolar el job.
 */
export interface PatternDefinition {
  code: PatternCode;
  group: PatternGroup;
  scanner: string;
  name: string;
  description: string;
  direction: PatternDirection;
  short_label: string;
  params: PatternParamSpec[];
  required_features: string[];
}

// ---------------------------------------------------------------------------
// Configuracion de un escaneo
// ---------------------------------------------------------------------------

/**
 * `PatternSelection`. Un patron elegido con sus parametros ya resueltos.
 *
 * Viaja en los tres sentidos con la misma forma: entrada del POST, contenido
 * de la columna JSONB `pattern_scan_jobs.patterns_config` y salida en los jobs.
 * Los parametros vienen rellenos y recortados a min/max por el backend
 * (`PatternDefinition.resolve_params`), asi que aqui siempre estan presentes.
 */
export interface PatternSelection {
  code: PatternCode;
  params: Record<string, number>;
}

/** `PatternScanConfig`. Cuerpo del POST /scans. */
export interface PatternScanConfig {
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  patterns: PatternSelection[];
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export type PatternScanJobStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

/**
 * Estados en los que el WebSocket de logs cierra por si mismo: el backend
 * hace `websocket.close()` cuando los ve. Un job que llega aqui no va a
 * emitir mas logs, y reconectar solo gastaria reintentos.
 */
export const PATTERN_TERMINAL_STATUSES: readonly PatternScanJobStatus[] = [
  "completed",
  "failed",
  "cancelled",
];

/**
 * `PatternScanJobListItem`. Fila de `GET /scans`.
 *
 * No trae `error_message` ni `updated_at`: la lista es un resumen y el detalle
 * va en `GET /scans/{id}`. La columna `patterns_config` conserva el nombre
 * `config` porque es el de la columna real, no un error de tipeo.
 */
export interface PatternScanJobListItem {
  id: string;
  status: PatternScanJobStatus;
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  patterns_config: PatternSelection[];
  total_candles: number;
  processed_candles: number;
  created_at: string;
  finished_at: string | null;
}

/** `PatternScanJobListOut`. */
export interface PatternScanJobListOut {
  jobs: PatternScanJobListItem[];
  total: number;
}

/**
 * `PatternScanJobResponse`. Detalle de un job, y respuesta de POST /scans,
 * /cancel y /requeue.
 *
 * Los tres devuelven esta misma forma, asi que cancelar o reencolar un job
 * deja el objeto listo para actualizar el estado en la lista sin refetch.
 */
export interface PatternScanJobResponse {
  id: string;
  status: PatternScanJobStatus;
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  patterns_config: PatternSelection[];
  started_at: string | null;
  finished_at: string | null;
  total_candles: number;
  processed_candles: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Ocurrencias
// ---------------------------------------------------------------------------

/**
 * `details` es la columna JSONB `metadata` de la tabla. Se llama `details` en
 * la API porque `metadata` es un atributo reservado de las clases
 * declarativas de SQLAlchemy y no se propaga al contrato a proposito; el nombre
 * de la columna en la base de datos sigue siendo `metadata`.
 *
 * Los valores son `number` o `string`: el scanner mete `direction: "bullish"`
 * junto a `macd: 2.0` y cosas asi. Nunca son `null`.
 *
 * La forma depende del patron:
 * - MACD / MA: `{ direction, macd, signal, diff }` y `{ direction, fast, slow, diff }`.
 * - RSI: `{ direction, rsi_value, threshold }`.
 * - Bollinger: `{ direction, close, band }`.
 * - Engulfing: `{ direction, open, close, prev_open, prev_close }`.
 */
export interface PatternOccurrenceDetails {
  direction?: PatternDirection;
  [key: string]: number | string | undefined;
}

/**
 * `PatternOccurrenceOut`. Una deteccion.
 *
 * No trae `direction` como campo propio: la direccion viaja dentro de
 * `details.direction`, que es lo que escribe el scanner. Para pintar markers
 * verdes y rojos hay que leer `details.direction`, o resolver el codigo contra
 * el catalogo, que es lo que hace el backend al construir los markers del
 * chart.
 */
export interface PatternOccurrence {
  timestamp: string;
  symbol: string;
  timeframe: string;
  pattern_name: PatternCode;
  scan_job_id: string;
  details: PatternOccurrenceDetails;
}

/** `PatternOccurrenceListOut`. */
export interface OccurrenceListOut {
  occurrences: PatternOccurrence[];
  total: number;
}

/** Una fila de los agregados de `by_pattern` / `by_symbol` / `by_timeframe`. */
export interface OccurrenceGroupCount {
  [key: string]: string | number | null;
}

/**
 * `PatternOccurrencesSummaryOut`. Agregados de `GET /occurrences/summary`.
 *
 * `by_pattern`, `by_symbol` y `by_timeframe` vienen como listas de objetos
 * libres y no como mapas tipados, porque cada una agrupa por columnas
 * distintas. Se estrechan en el punto de uso con el helper que corresponda.
 */
export interface OccurrenceSummary {
  total: number;
  distinct_patterns: number;
  distinct_symbols: number;
  first_occurrence: string | null;
  last_occurrence: string | null;
  bullish: number;
  bearish: number;
  by_pattern: OccurrenceGroupCount[];
  by_symbol: OccurrenceGroupCount[];
  by_timeframe: OccurrenceGroupCount[];
}

// ---------------------------------------------------------------------------
// Datos disponibles
// ---------------------------------------------------------------------------

/**
 * `PatternAvailableDataOut`. Un par (simbolo, timeframe) escaneable.
 *
 * `indicators` son los nombres de feature ya precalculados para el par, no
 * codigos de patron. Es lo que hay que cruzar con
 * `PatternDefinition.required_features` para avisar *antes* de encolar un
 * escaneo de que falta una feature, en vez de dejar que el job falle con
 * `MissingFeaturesError` y haya que leer los logs para enterarse.
 */
export interface PatternAvailableData {
  symbol: string;
  timeframe: string;
  candles: number;
  first_candle: string;
  last_candle: string;
  indicators: string[];
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------

export type PatternLogLevel = "info" | "warning" | "error";

/**
 * `PatternScanLogOut`. Un log del escaneo, tal y como llega por el WebSocket.
 *
 * `progress` es un porcentaje entero o `null` en los logs que no son de avance.
 * El backend emite el campo siempre, asi que llega como `null` y no se
 * omite.
 */
export interface PatternScanLog {
  id: string;
  timestamp: string;
  level: PatternLogLevel;
  message: string;
  progress: number | null;
}

/**
 * Marker para lightweight-charts, ya resuelto por el backend.
 *
 * `position` y `shape` son los literales que espera la libreria, no valores
 * inventados aqui: el backend decide bullish -> `belowBar` + `arrowUp` en
 * verde, y bearish -> `aboveBar` + `arrowDown` en rojo. Duplicar esa logica en
 * el frontend haria que un cambio de color se aplicara a un sitio y a otro no.
 */
export interface PatternChartMarker {
  timestamp: string;
  pattern_name: PatternCode;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown";
  color: string;
  text: string;
  details: PatternOccurrenceDetails;
}

/**
 * `GET /scans/{id}/chart` es **la misma ruta** que `GET /patterns/chart`, con los
 * parametros del escaneo por defecto. Su tipo es, por tanto, el mismo.
 *
 * Se conserva el alias porque el nombre aparece en dos sitios mas, y borrar el
 * simbolo seria ruido por el gusto de borrar simbolos. Lo que no se conserva es
 * la **interfaz duplicada**: tener el contrato del grafico en dos sitios es
 * exactamente como se cuela un cambio en uno y no en el otro, y ya paso — la
 * primera vez que esta ruta dejo de declarar `response_model`, el unico contrato
 * era este fichero y ninguna clave nueva se contrastaba contra nada.
 *
 * `indicators` sigue siendo un mapa de nombre a serie y no una lista: las series
 * con NaN ya vienen recortadas (`dropna`), asi que hay puntos sueltos y
 * lightweight-charts los une por tiempo.
 */
export type PatternChartData = ChartData;
