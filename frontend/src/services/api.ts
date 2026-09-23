import axios from "axios";

import type {
  BinanceSymbol,
  ImportConfig,
  ImportJob,
  ImportStats,
  JobListResponse,
  PreviewResponse,
  StartImportResponse,
} from "../types/dataImport";

const apiClient = axios.create({
  baseURL: "/api/v1/data-import",
  timeout: 30000,
});

export interface JobListQuery {
  status?: string;
  symbol?: string;
  timeframe?: string;
  page?: number;
  page_size?: number;
}

export async function startImport(config: ImportConfig): Promise<StartImportResponse> {
  const { data } = await apiClient.post<StartImportResponse>("/start", config);
  return data;
}

export async function listJobs(query: JobListQuery = {}): Promise<JobListResponse> {
  const { data } = await apiClient.get<JobListResponse>("/list", { params: query });
  return data;
}

export async function getJobStatus(jobId: string): Promise<ImportJob> {
  const { data } = await apiClient.get<ImportJob>(`/status/${jobId}`);
  return data;
}

export async function getSymbols(): Promise<BinanceSymbol[]> {
  const { data } = await apiClient.get<BinanceSymbol[]>("/symbols");
  return data;
}

export async function previewJob(
  jobId: string,
  options?: { symbol?: string; timeframe?: string; limit?: number },
): Promise<PreviewResponse> {
  const { data } = await apiClient.get<PreviewResponse>(`/preview/${jobId}`, { params: options });
  return data;
}

export async function getStats(jobId: string): Promise<ImportStats> {
  const { data } = await apiClient.get<ImportStats>(`/stats/${jobId}`);
  return data;
}

export async function cancelImport(jobId: string): Promise<ImportJob> {
  const { data } = await apiClient.post<ImportJob>(`/cancel/${jobId}`);
  return data;
}

export async function retryJob(jobId: string): Promise<StartImportResponse> {
  const { data } = await apiClient.post<StartImportResponse>(`/retry/${jobId}`);
  return data;
}