export type FeatureJobStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

export interface IndicatorConfig {
  name: string;
  params: Record<string, number>;
}

export interface FeatureJobConfig {
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  indicators: IndicatorConfig[];
}

export interface FeatureJobListItem {
  id: string;
  status: FeatureJobStatus;
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  indicators_config: IndicatorConfig[];
  total_candles: number;
  processed_candles: number;
  created_at: string;
  finished_at: string | null;
}

export interface FeatureJobResponse {
  id: string;
  status: FeatureJobStatus;
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  indicators_config: IndicatorConfig[];
  started_at: string | null;
  finished_at: string | null;
  total_candles: number;
  processed_candles: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeatureJobListOut {
  jobs: FeatureJobListItem[];
  total: number;
}

export interface FeaturePreviewRow {
  timestamp: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  indicators: Record<string, number>;
}

export interface FeaturePreviewOut {
  job_id: string;
  symbol: string;
  timeframe: string;
  rows: FeaturePreviewRow[];
}

export interface FeatureLog {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
  progress: number | null;
}

export interface BatchDeleteBody {
  job_ids: string[];
}
