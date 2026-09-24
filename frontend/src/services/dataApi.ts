import axios from "axios";

import type {
  DataDeleteResponse,
  DataPreviewResponse,
  DataSummaryResponse,
} from "../types/data";

const apiClient = axios.create({
  baseURL: "/api/v1/data",
  timeout: 30000,
});

export async function getDataSummary(): Promise<DataSummaryResponse> {
  const { data } = await apiClient.get<DataSummaryResponse>("/summary");
  return data;
}

export async function previewData(
  symbol: string,
  timeframe: string,
  limit = 50,
): Promise<DataPreviewResponse> {
  const { data } = await apiClient.get<DataPreviewResponse>("/preview", {
    params: { symbol, timeframe, limit },
  });
  return data;
}

export async function deleteData(
  symbol: string,
  timeframe: string,
): Promise<DataDeleteResponse> {
  const { data } = await apiClient.delete<DataDeleteResponse>(
    `/${symbol}/${timeframe}`,
  );
  return data;
}