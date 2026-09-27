export type ImportStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

export type ImportMode = "merge" | "append" | "overwrite";

export type LogLevel = "info" | "warning" | "error";

export interface ImportConfig {
  symbols: string[];
  timeframes: string[];
  date_from: string;
  date_to: string;
  import_mode: ImportMode;
}

export interface ImportJobCombination {
  id: string;
  symbol: string;
  timeframe: string;
  status: ImportStatus;
  started_at: string | null;
  finished_at: string | null;
  candles_downloaded: number;
  candles_inserted: number;
  candles_updated: number;
  candles_skipped: number;
  first_candle_at: string | null;
  last_candle_at: string | null;
  error_message: string | null;
}

export interface ImportLog {
  id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
  progress: number | null;
}

export interface ImportJob {
  id: string;
  status: ImportStatus;
  source_type: string;
  started_at: string | null;
  finished_at: string | null;
  symbols: string[];
  timeframes: string[];
  date_from: string;
  date_to: string;
  import_mode: ImportMode;
  total_combinations: number;
  completed_combinations: number;
  failed_combinations: number;
  total_candles_downloaded: number;
  total_candles_inserted: number;
  total_candles_updated: number;
  total_candles_skipped: number;
  error_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  combinations: ImportJobCombination[];
}

export interface JobListItem {
  id: string;
  status: ImportStatus;
  symbols: string[];
  timeframes: string[];
  date_from: string;
  date_to: string;
  import_mode: ImportMode;
  total_combinations: number;
  completed_combinations: number;
  failed_combinations: number;
  total_candles_downloaded: number;
  total_candles_inserted: number;
  total_candles_updated: number;
  total_candles_skipped: number;
  created_at: string;
  finished_at: string | null;
}

export interface JobListResponse {
  jobs: JobListItem[];
  total: number;
}

export interface BinanceSymbol {
  symbol: string;
  status: string;
  base_asset: string;
  quote_asset: string;
}

export interface PreviewCandle {
  timestamp: string;
  symbol: string;
  timeframe: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface PreviewResponse {
  job_id: string;
  symbol: string | null;
  timeframe: string | null;
  rows: PreviewCandle[];
}

export interface ImportStats {
  job_id: string;
  total_candles_downloaded: number;
  total_candles_inserted: number;
  total_candles_updated: number;
  total_candles_skipped: number;
  combinations_completed: number;
  combinations_failed: number;
  quality: {
    discarded_candles: number;
    error_kinds: Record<string, number>;
  };
  gaps: GapInfo[];
}

export interface GapInfo {
  symbol: string;
  timeframe: string;
  from: string;
  to: string;
  missing: number;
}

export interface StartImportResponse {
  job_id: string;
}
