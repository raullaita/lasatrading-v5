import axios from "axios";

import type {
  WalkForwardCreateIn,
  WalkForwardEquitySeries,
  WalkForwardReport,
  WalkForwardRun,
  WalkForwardRunListOut,
} from "../types/walkForward";

/**
 * Cliente del modulo de walk-forward.
 *
 * Mismo patron que `backtestsApi`: un `axios.create` propio con `baseURL`
 * relativo que resuelve el proxy de Vite. El `timeout` de 30 s no es
 * arbitrario: el POST devuelve 202 con el `id` y el trabajo corre en la tarea
 * Celery, asi que la peticion no espera al motor. Si el POST tardara lo que
 * tarda el walk-forward, este timeout seria el que cortaria, dejaria el run a
 * medias y dejaria la pantalla sin saber que paso.
 */
const apiClient = axios.create({
  baseURL: "/api/v1/walk-forward",
  timeout: 30000,
});

export async function createWalkForward(config: WalkForwardCreateIn): Promise<WalkForwardRun> {
  const { data } = await apiClient.post<WalkForwardRun>("/runs", config);
  return data;
}

export async function getWalkForwards(page = 1, pageSize = 50): Promise<WalkForwardRunListOut> {
  const { data } = await apiClient.get<WalkForwardRunListOut>("/runs", {
    params: { page, page_size: pageSize },
  });
  return data;
}

/**
 * Informe completo: cabecera, ventanas y candidatas.
 *
 * **409** mientras el run no haya terminado. No es un informe con menos filas,
 * es un informe cuyo veredicto no se puede leer, asi que el error se propaga y
 * quien llama decide que pintar en vez de enseñando una tabla vacia que parece
 * un resultado.
 */
export async function getWalkForwardReport(runId: string): Promise<WalkForwardReport> {
  const { data } = await apiClient.get<WalkForwardReport>(`/runs/${runId}`);
  return data;
}

/**
 * Curva OOS encadenada y benchmark encadenado.
 *
 * `maxPoints` va en la peticion y no como un tope del servidor porque quien
 * dibuja sabe cuantos pixeles tiene, y una curva de 44.000 puntos renderizada en
 * 900 pixeles no gana nada: el backend ya submuestrea conservando extremos y el
 * ultimo punto, que es el que dice el `equity_final` de la cabecera.
 */
export async function getWalkForwardEquity(
  runId: string,
  maxPoints?: number,
): Promise<WalkForwardEquitySeries> {
  const { data } = await apiClient.get<WalkForwardEquitySeries>(`/runs/${runId}/equity`, {
    params: maxPoints ? { max_points: maxPoints } : {},
  });
  return data;
}

/** **409** si el run ya termino: no se puede cancelar un informe que ya existe. */
export async function cancelWalkForward(runId: string): Promise<WalkForwardRun> {
  const { data } = await apiClient.post<WalkForwardRun>(`/runs/${runId}/cancel`);
  return data;
}
