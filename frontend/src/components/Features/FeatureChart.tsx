import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  type CandlestickData,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useTheme } from "../../theme/theme";
import type { FeaturePreviewRow } from "../../types/features";

const INDICATOR_COLORS = [
  "#f59e0b",
  "#10b981",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
  "#f97316",
];

const THEME_COLORS = {
  light: {
    background: "#f8fafc",
    text: "#64748b",
    grid: "#e2e8f0",
    border: "#cbd5e1",
  },
  dark: {
    background: "#0f172a",
    text: "#94a3b8",
    grid: "#1e293b",
    border: "#334155",
  },
} as const;

type Ohlc = {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
};

type PreparedRow = {
  seconds: number;
  time: Time;
  ohlc: Ohlc | null;
  indicators: Record<string, number>;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function toUnixSeconds(iso: string): number | null {
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

function prepareRows(data: FeaturePreviewRow[]): PreparedRow[] {
  const byTime = new Map<number, PreparedRow>();

  for (const row of data) {
    const seconds = toUnixSeconds(row.timestamp);
    if (seconds === null) continue;

    let entry = byTime.get(seconds);
    if (!entry) {
      entry = { seconds, time: seconds as Time, ohlc: null, indicators: {} };
      byTime.set(seconds, entry);
    }

    if (
      entry.ohlc === null &&
      isFiniteNumber(row.open) &&
      isFiniteNumber(row.high) &&
      isFiniteNumber(row.low) &&
      isFiniteNumber(row.close)
    ) {
      entry.ohlc = {
        time: entry.time,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
      };
    }

    for (const [name, value] of Object.entries(row.indicators)) {
      if (isFiniteNumber(value)) entry.indicators[name] = value;
    }
  }

  return Array.from(byTime.values()).sort((a, b) => a.seconds - b.seconds);
}

export function FeatureChart({
  data,
  symbol,
  timeframe,
}: {
  data: FeaturePreviewRow[];
  symbol: string;
  timeframe: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const { theme } = useTheme();

  const rows = useMemo(() => prepareRows(data), [data]);

  const plottable = useMemo(
    () =>
      rows.some(
        (row) => row.ohlc !== null || Object.keys(row.indicators).length > 0
      ),
    [rows]
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !plottable) return;

    const colors = THEME_COLORS[theme];
    let chart: IChartApi | null = null;
    let resizeObserver: ResizeObserver | null = null;

    try {
      const api: IChartApi = createChart(container, {
        layout: {
          background: { color: colors.background },
          textColor: colors.text,
        },
        grid: {
          vertLines: { color: colors.grid },
          horzLines: { color: colors.grid },
        },
        rightPriceScale: { borderColor: colors.border },
        timeScale: { borderColor: colors.border },
        width: container.clientWidth,
        height: 400,
      });
      chart = api;

      const candleData: CandlestickData[] = [];
      for (const row of rows) {
        if (row.ohlc) candleData.push(row.ohlc);
      }
      if (candleData.length > 0) {
        api.addCandlestickSeries().setData(candleData);
      }

      const indicatorNames: string[] = [];
      for (const row of rows) {
        for (const name of Object.keys(row.indicators)) {
          if (!indicatorNames.includes(name)) indicatorNames.push(name);
        }
      }

      indicatorNames.forEach((indicatorName, colorIdx) => {
        const lineData: LineData[] = [];
        for (const row of rows) {
          const value = row.indicators[indicatorName];
          if (isFiniteNumber(value)) lineData.push({ time: row.time, value });
        }
        if (lineData.length === 0) return;

        const series = api.addLineSeries({
          color: INDICATOR_COLORS[colorIdx % INDICATOR_COLORS.length],
          lineWidth: 1,
          title: indicatorName,
        });
        series.setData(lineData);
      });

      api.timeScale().fitContent();
      chartRef.current = chart;
      setChartError(null);

      resizeObserver = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width: containerRef.current.clientWidth,
          });
        }
      });
      resizeObserver.observe(container);
    } catch (err) {
      if (chart) chart.remove();
      chartRef.current = null;
      setChartError(
        err instanceof Error ? err.message : "No se pudo renderizar el gráfico."
      );
      return;
    }

    return () => {
      resizeObserver?.disconnect();
      chart?.remove();
      chartRef.current = null;
    };
  }, [rows, plottable, symbol, timeframe, theme]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h3 className="mb-3 text-sm font-bold text-slate-900 dark:text-slate-100">
        {symbol} · {timeframe} — Velas con indicadores
      </h3>
      <div ref={containerRef} className="w-full" />
      {rows.length === 0 && (
        <p className="py-8 text-center text-slate-400 dark:text-slate-500">
          Sin datos para graficar
        </p>
      )}
      {rows.length > 0 && !plottable && (
        <p className="py-8 text-center text-sm text-amber-600 dark:text-amber-400">
          Se recibieron {rows.length} filas, pero ninguna contiene valores numéricos
          válidos para graficar.
        </p>
      )}
      {rows.length > 0 && plottable && chartError && (
        <p className="py-4 text-center text-sm text-rose-600 dark:text-rose-400">
          Error al renderizar el gráfico: {chartError}
        </p>
      )}
    </div>
  );
}
