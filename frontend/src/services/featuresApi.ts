import type { IndicatorAvailabilityList } from "../types/chart";
import axios from "axios";

import type {
  FeatureJobConfig,
  FeatureJobListOut,
  FeatureJobResponse,
  FeaturePreviewOut,
} from "../types/features";

const apiClient = axios.create({
  baseURL: "/api/v1/features",
  timeout: 30000,
});

export async function createFeatureJob(config: FeatureJobConfig): Promise<FeatureJobResponse> {
  const { data } = await apiClient.post<FeatureJobResponse>("/jobs", config);
  return data;
}

export async function getFeatureJobs(
  filters: {
    status?: string;
    symbol?: string;
    timeframe?: string;
    sort_by?: string;
    sort_order?: string;
    page?: number;
    page_size?: number;
  } = {},
): Promise<FeatureJobListOut> {
  const { data } = await apiClient.get<FeatureJobListOut>("/jobs", {
    params: filters,
  });
  return data;
}

export async function getFeatureJob(jobId: string): Promise<FeatureJobResponse> {
  const { data } = await apiClient.get<FeatureJobResponse>(`/jobs/${jobId}`);
  return data;
}

export async function getFeatureJobPreview(
  jobId: string,
  limit: number = 100,
): Promise<FeaturePreviewOut> {
  const { data } = await apiClient.get<FeaturePreviewOut>(`/jobs/${jobId}/preview`, {
    params: { limit },
  });
  return data;
}

export async function cancelFeatureJob(jobId: string): Promise<FeatureJobResponse> {
  const { data } = await apiClient.post<FeatureJobResponse>(`/jobs/${jobId}/cancel`);
  return data;
}

export async function deleteFeatureJob(
  jobId: string,
): Promise<{ deleted: boolean; job_id: string }> {
  const { data } = await apiClient.delete<{ deleted: boolean; job_id: string }>(`/jobs/${jobId}`);
  return data;
}

export async function deleteFeatureJobsBatch(jobIds: string[]): Promise<{ deleted_count: number }> {
  const { data } = await apiClient.delete<{ deleted_count: number }>(`/jobs/batch`, {
    data: { job_ids: jobIds },
  });
  return data;
}

export async function clearFeatureJobLogs(jobId: string): Promise<{ deleted: number }> {
  const { data } = await apiClient.delete<{ deleted: number }>(`/jobs/${jobId}/logs`);
  return data;
}

export async function requeueFeatureJob(jobId: string): Promise<FeatureJobResponse> {
  const { data } = await apiClient.post<FeatureJobResponse>(`/jobs/${jobId}/requeue`);
  return data;
}

export async function getAvailableData(): Promise<{ symbol: string; timeframe: string }[]> {
  const { data } = await apiClient.get<{ symbol: string; timeframe: string }[]>(`/data/available`);
  return data;
}

/**
 * Indicadores ya calculados para un par, con su cobertura real.
 *
 * El explorador lo usa para poblar el selector, y la parte que importa no es la
 * lista sino el **rango** de cada uno: `EMA_50` existe para BTCUSDT pero solo
 * desde julio de 2026, y ofrecerlo en un rango de 2022 hace que el usuario
 * descubra la falta cuando ya esta mirando el grafico.
 */
export async function getIndicatorAvailability(
  symbol: string,
  timeframe: string,
): Promise<IndicatorAvailabilityList> {
  const { data } = await apiClient.get<IndicatorAvailabilityList>("/data/indicators", {
    params: { symbol, timeframe },
  });
  return data;
}
