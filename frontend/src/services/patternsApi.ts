import axios from "axios";

import type {
  OccurrenceListOut,
  OccurrenceSummary,
  PatternAvailableData,
  PatternChartData,
  PatternDefinition,
  PatternScanConfig,
  PatternScanJobListOut,
  PatternScanJobResponse,
} from "../types/patterns";

/**
 * Cliente del modulo de patrones.
 *
 * Un `axios.create` propio, igual que features: el `baseURL` relativo
 * (`/api/v1/patterns`) lo resuelve el proxy de Vite, asi que el mismo codigo
 * funciona en desarrollo contra localhost:8000 y en produccion contra el
 * dominio real sin tocar nada.
 *
 * `timeout` de 30 s. Ninguna operacion de este modulo deberia tardar eso: lo
 * lento es el escaneo, que ocurre en la tarea Celery y se sigue por polling o
 * WebSocket, no por esperar la respuesta de un POST.
 */
const apiClient = axios.create({
  baseURL: "/api/v1/patterns",
  timeout: 30000,
});

/** Filtros de `GET /scans`. Todos opcionales. */
export interface PatternScanFilters {
  status?: string;
  symbol?: string;
  timeframe?: string;
  /** Columna por la que ordenar. El backend tiene lista blanca: 400 si no existe. */
  sort_by?: string;
  sort_order?: "asc" | "desc";
  page?: number;
  /** Tope del backend: 100. */
  page_size?: number;
}

/**
 * Filtros que aceptan `GET /occurrences` **y** `GET /occurrences/summary`.
 *
 * `patterns` va como CSV en la query, no como array: el backend lo parsea con
 * `_split_csv`. Se serializa aqui con `csv()` en vez de confiar en el
 * `paramsSerializer` de axios, que con arrays repetiria la clave y FastAPI se
 * quedaria solo con el ultimo valor.
 *
 * `job_id` **no** esta aqui a proposito: `occurrences_summary` no lo declara, y
 * mandarlo seria peor que no mandarlo, porque FastAPI descarta en silencio los
 * query params desconocidos y el resumen saldria de todo el histórico del
 * símbolo en lugar de del job, sin un solo error por el camino.
 */
export interface OccurrenceFilters {
  symbol?: string;
  timeframe?: string;
  patterns?: string[];
  date_from?: string;
  date_to?: string;
}

/** Filtros de la tabla maestra. Añade lo que el resumen no soporta. */
export interface OccurrenceListFilters extends OccurrenceFilters {
  job_id?: string;
  /**
   * Paginacion de `GET /occurrences`. No la acepta `getOccurrencesSummary`, que
   * devuelve solo contadores.
   */
  page?: number;
  /** Tope del backend: 500. */
  page_size?: number;
}

/** Filtros de `GET /scans/{id}/chart`. */
export interface PatternChartParams {
  /** Por defecto, los del propio job. */
  symbol?: string;
  timeframe?: string;
  date_from?: string;
  date_to?: string;
  /** Indicadores a superponer, CSV. Se ignoran los que no existan. */
  features?: string[];
  /** Patrones a marcar, CSV. */
  patterns?: string[];
}

/** Pagina de `GET /scans/{id}/occurrences`, que no admite mas filtros. */
export interface JobOccurrenceFilters {
  page?: number;
  /** Tope del backend: 500. */
  page_size?: number;
}

function csv(values?: string[]): string | undefined {
  return values && values.length > 0 ? values.join(",") : undefined;
}

/**
 * Crea un escaneo y lo encola.
 *
 * El backend responde 201 con el job ya en `pending`; el escaneo corre en la
 * tarea Celery. El 422 de `PatternScanConfig` (patrones duplicados, codigo
 * desconocido, lista vacia) es el error que mas se va a ver, asi que conviene
 * validar en el formulario antes de llegar aqui.
 */
export async function createPatternScan(
  config: PatternScanConfig,
): Promise<PatternScanJobResponse> {
  const { data } = await apiClient.post<PatternScanJobResponse>("/scans", config);
  return data;
}

export async function getPatternScans(
  filters: PatternScanFilters = {},
): Promise<PatternScanJobListOut> {
  const { data } = await apiClient.get<PatternScanJobListOut>("/scans", {
    params: filters,
  });
  return data;
}

export async function getPatternScan(jobId: string): Promise<PatternScanJobResponse> {
  const { data } = await apiClient.get<PatternScanJobResponse>(`/scans/${jobId}`);
  return data;
}

/**
 * Ocurrencias de un job concreto.
 *
 * Solo admite paginacion: el job ya fija simbolo, timeframe y rango, asi que
 * filtrar por ellos seria redundante. Para buscar entre todos los jobs esta
 * `getOccurrences`.
 */
export async function getPatternScanOccurrences(
  jobId: string,
  filters: JobOccurrenceFilters = {},
): Promise<OccurrenceListOut> {
  const { data } = await apiClient.get<OccurrenceListOut>(`/scans/${jobId}/occurrences`, {
    params: filters,
  });
  return data;
}

export async function getPatternScanChart(
  jobId: string,
  params: PatternChartParams = {},
): Promise<PatternChartData> {
  const { data } = await apiClient.get<PatternChartData>(`/scans/${jobId}/chart`, {
    params: { ...params, features: csv(params.features), patterns: csv(params.patterns) },
  });
  return data;
}

/** 400 si el job ya esta en `completed`, `failed` o `cancelled`. */
export async function cancelPatternScan(jobId: string): Promise<PatternScanJobResponse> {
  const { data } = await apiClient.post<PatternScanJobResponse>(`/scans/${jobId}/cancel`);
  return data;
}

/**
 * Relanza un job. Acepta `pending`, `processing` y `failed`.
 *
 * `failed` es el caso interesante: si el job murio por `MissingFeaturesError`,
 * el camino es calcular las features que faltaban y reencolar *ese* job, no
 * crear otro desde cero y perder el rango ya elegido. El backend limpia
 * `error_message` y los contadores al reencolar.
 */
export async function requeuePatternScan(jobId: string): Promise<PatternScanJobResponse> {
  const { data } = await apiClient.post<PatternScanJobResponse>(`/scans/${jobId}/requeue`);
  return data;
}

export async function deletePatternScan(
  jobId: string,
): Promise<{ deleted: boolean; job_id: string }> {
  const { data } = await apiClient.delete<{ deleted: boolean; job_id: string }>(`/scans/${jobId}`);
  return data;
}

/**
 * Borra varios jobs. Las ocurrencias y los logs caen por `ON DELETE CASCADE`,
 * tambien sobre los chunks de la hypertable, asi que no hay que limpiarlos.
 */
export async function deletePatternScansBatch(
  jobIds: string[],
): Promise<{ deleted_count: number }> {
  const { data } = await apiClient.delete<{ deleted_count: number }>("/scans/batch", {
    data: { job_ids: jobIds },
  });
  return data;
}

export async function clearPatternScanLogs(jobId: string): Promise<{ deleted: number }> {
  const { data } = await apiClient.delete<{ deleted: number }>(`/scans/${jobId}/logs`);
  return data;
}

/**
 * Catalogo de los diez patrones con sus parametros y features exigidas.
 *
 * Se desenvuelve el envoltorio `PatternCatalogOut` para devolver el array
 * directo, que es como lo consume el selector. Un solo patron sufijo
 * con direccion, p. ej. `RSI_EXIT_OVERSOLD`, es `bullish`: el nombre dice el
 * estado del que se sale, no la direccion a la que se entra.
 */
export async function getPatternCatalog(): Promise<PatternDefinition[]> {
  const { data } = await apiClient.get<{ patterns: PatternDefinition[] }>("/catalog");
  return data.patterns;
}

/**
 * Pares (simbolo, timeframe) escaneables y features ya precalculadas.
 *
 * Se devuelve el array y no el envoltorio `{ data: [...] }`. Los `indicators`
 * de cada par son nombres de feature, no codigos de patron, y hay que
 * cruzarlos con `PatternDefinition.required_features` para poder avisar de que
 * falta `EMA_50` antes de que el POST /scans devuelva 400.
 */
export async function getAvailableData(): Promise<PatternAvailableData[]> {
  const { data } = await apiClient.get<{ data: PatternAvailableData[] }>("/data/available");
  return data.data;
}

/** Tabla maestra de ocurrencias de todos los jobs. */
export async function getOccurrences(
  filters: OccurrenceListFilters = {},
): Promise<OccurrenceListOut> {
  const { data } = await apiClient.get<OccurrenceListOut>("/occurrences", {
    params: { ...filters, patterns: csv(filters.patterns) },
  });
  return data;
}

/**
 * Agregados para las tarjetas de resumen.
 *
 * Sin paginacion a todas. El tipo de entrada no ofrece `page`, pero TypeScript
 * es estructural: un `OccurrenceListFilters` es asignable a `OccurrenceFilters`
 * y los campos de mas se cuelan tal cual en la query. Se separan aqui a mano
 * para que el endpoint no reciba lo que no declara, en vez de confiar en que
 * nadie pase el objeto equivocado.
 */
export async function getOccurrencesSummary(
  filters: OccurrenceFilters = {},
): Promise<OccurrenceSummary> {
  const { page, page_size, ...rest } = filters as OccurrenceListFilters;
  void page;
  void page_size;
  const { data } = await apiClient.get<OccurrenceSummary>("/occurrences/summary", {
    params: { ...rest, patterns: csv(rest.patterns) },
  });
  return data;
}
