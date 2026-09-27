export interface DataGroupSummary {
  symbol: string;
  timeframe: string;
  total_candles: number;
  first_timestamp: string;
  last_timestamp: string;
}

export interface DataSummaryResponse {
  groups: DataGroupSummary[];
}

export interface DataCandle {
  timestamp: string;
  symbol: string;
  timeframe: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface DataPreviewResponse {
  symbol: string;
  timeframe: string;
  rows: DataCandle[];
}

export interface DataDeleteResponse {
  symbol: string;
  timeframe: string;
  deleted: number;
}
