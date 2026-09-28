import axios from "axios";

import type {
  BacktestAvailableScan,
  BacktestCreateIn,
  BacktestEquitySeries,
  BacktestRunListOut,
  BacktestRunResponse,
  BacktestSummary,
  BacktestTradeListOut,
  BacktestRunStatus,
  ExitReason,
  TradeDirection,
} from "../types/backtesting";

/**
 * Cliente del modulo de backtesting.
 *
 * Mismo patrón que `patternsApi`: un `axios.create` propio con `baseURL`
 * relativo que resuelve el proxy de Vite. `timeout` de 30 s: lo lento de este
 * modulo es la simulacion, que corre en la tarea `backtest.run_backtest` y se
 * sigue por polling y WebSocket, no esperando la respuesta de un POST.
 */
const apiClient = axios.create({
  baseURL: "/api/v1/backtests",
  timeout: 30000,
});

/** Filtros de `GET /backtests`. `sort_by` tiene lista blanca en el backend. */
export interface BacktestFilters {
  status?: BacktestRunStatus;
  scan_job_id?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  page?: number;
  /** Tope del backend: 100. */
  page_size?: number;
}

/** Filtros de `GET /backtests/{id}/trades`. */
export interface TradeFilters {
  /** Los patrones van repetidos (`pattern=A&pattern=B`), no como CSV. */
  pattern?: string[];
  direction?: TradeDirection[];
  exit_reason?: ExitReason[];
  sort_by?: string;
  sort_order?: "asc" | "desc";
  page?: number;
  /** Tope del backend: 200. */
  page_size?: number;
}

export async function createBacktest(config: BacktestCreateIn): Promise<BacktestRunResponse> {
  const { data } = await apiClient.post<BacktestRunResponse>("/", config);
  return data;
}

export async function getBacktests(filters: BacktestFilters = {}): Promise<BacktestRunListOut> {
  const { data } = await apiClient.get<BacktestRunListOut>("/", { params: filters });
  return data;
}

/** 400 si la columna de `sort_by` no esta en la lista blanca del router. */
export async function getBacktest(runId: string): Promise<BacktestRunResponse> {
  const { data } = await apiClient.get<BacktestRunResponse>(`/${runId}`);
  return data;
}

/**
 * Escaneos completados que admiten simulacion.
 *
 * Solo los `completed`: uno en curso no tiene todas sus ocurrencias, y simular
 * contra un subconjunto daria un resultado que luego no se reproduce.
 */
export async function getBacktestAvailableScans(): Promise<BacktestAvailableScan[]> {
  const { data } = await apiClient.get<{ scans: BacktestAvailableScan[] }>("/available-scans");
  return data.scans;
}

export async function getBacktestSummary(runId: string): Promise<BacktestSummary> {
  const { data } = await apiClient.get<BacktestSummary>(`/${runId}/summary`);
  return data;
}

/**
 * Curva de equity submuestreada. `max_points` es un tope: la respuesta dice
 * cuantos puntos reales hay (`total_points`), y el último de la serie enviada
 * es siempre el del cierre real (fix de backend). Si no se pasa, se devuelve
 * la curva entera.
 */
export async function getBacktestEquity(
  runId: string,
  maxPoints?: number,
): Promise<BacktestEquitySeries> {
  const { data } = await apiClient.get<BacktestEquitySeries>(`/${runId}/equity`, {
    params: maxPoints ? { max_points: maxPoints } : undefined,
  });
  return data;
}

export async function getBacktestTrades(
  runId: string,
  filters: TradeFilters = {},
): Promise<BacktestTradeListOut> {
  const { data } = await apiClient.get<BacktestTradeListOut>(`/${runId}/trades`, {
    params: { ...filters },
  });
  return data;
}

/** 409 si el run no esta en `pending`/`processing`/`failed`. */
export async function cancelBacktest(runId: string): Promise<BacktestRunResponse> {
  const { data } = await apiClient.post<BacktestRunResponse>(`/${runId}/cancel`);
  return data;
}

/** 400 si el run no esta en `pending`/`processing`/`failed`. */
export async function requeueBacktest(runId: string): Promise<BacktestRunResponse> {
  const { data } = await apiClient.post<BacktestRunResponse>(`/${runId}/requeue`);
  return data;
}

export async function deleteBacktest(runId: string): Promise<{ deleted: boolean; run_id: string }> {
  const { data } = await apiClient.delete<{ deleted: boolean; run_id: string }>(`/${runId}`);
  return data;
}

/** Cuerpo del borrado masivo: la clave es `run_ids`, no `job_ids`. */
export async function deleteBacktestsBatch(
  runIds: string[],
): Promise<{ deleted: number; requested: number }> {
  const { data } = await apiClient.delete<{ deleted: number; requested: number }>("/", {
    data: { run_ids: runIds },
  });
  return data;
}
