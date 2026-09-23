export interface TimeframeGroup {
  label: string;
  data: string[];
  default: string;
}

export const TIMEFRAME_GROUPS: TimeframeGroup[] = [
  { label: "Intradía", data: ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"], default: "1h" },
  { label: "Swing", data: ["6h", "8h", "12h", "1d"], default: "4h" },
  { label: "Posicional", data: ["3d", "1w"], default: "1d" },
];

export const DEFAULT_TIMEFRAMES = TIMEFRAME_GROUPS.map((g) => g.default);