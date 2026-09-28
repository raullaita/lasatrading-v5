import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";

import { isFiniteNumber, toUnixSeconds } from "../Patterns/patternUtils";
import { useTheme } from "../../theme/theme";
import type { BacktestEquityPoint } from "../../types/backtesting";
import { formatMoney, toNumber } from "../../utils/format";

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

/**
 * Curva de equity de un run.
 *
 * Usa el mismo `createChart` que `PatternChart` (lightweight-charts no admite
 * reuso del mismo chart), pero con una serie de líneas y sin velas: aqui no
 * hay ohclv, solo el capital por vela simulado. El `equity` llega como string
 * (Decimal) y la linea se pinta con los extremos recortados — un run sobre
 * mil velas renderizado a 100 puntos se ve igual que uno corto, que es justo
 * lo que interesa del progreso.
 */
export function EquityChart({ points }: { points: BacktestEquityPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const { theme } = useTheme();

  const lineData = useMemo<LineData[]>(() => {
    const rows: LineData[] = [];
    for (const point of points) {
      const seconds = toUnixSeconds(point.timestamp);
      const value = toNumber(point.equity);
      if (seconds === null || value === null || !isFiniteNumber(value)) continue;
      rows.push({ time: seconds as Time, value });
    }
    // El backend viene ordenado, pero un sort defensivo evita romper el render.
    return rows.sort((a, b) => (a.time as number) - (b.time as number));
  }, [points]);

  const first = useMemo(() => toNumber(points[0]?.equity), [points]);
  const last = useMemo(() => toNumber(points[points.length - 1]?.equity), [points]);
  /** ¿El run acabó por encima de donde empezó? Pinta la línea verde o roja. */
  const up = last !== null && first !== null && last >= first;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || lineData.length === 0) return;

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
        height: 360,
      });
      chart = api;

      const series: ISeriesApi<"Line"> = api.addLineSeries({
        color: up ? "#10b981" : "#ef4444",
        lineWidth: 2,
      });
      series.setData(lineData);
      api.timeScale().fitContent();

      chartRef.current = chart;
      setChartError(null);

      resizeObserver = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      resizeObserver.observe(container);
    } catch (err) {
      if (chart) chart.remove();
      chartRef.current = null;
      setChartError(err instanceof Error ? err.message : "No se pudo renderizar el gráfico.");
      return;
    }

    return () => {
      resizeObserver?.disconnect();
      chart?.remove();
      chartRef.current = null;
    };
  }, [lineData, up, theme]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">Curva de equity</h3>
        {last !== null && (
          <span
            className={`text-sm font-semibold ${up ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}
          >
            {formatMoney(last)}
          </span>
        )}
      </div>
      <div ref={containerRef} className="w-full" />
      {lineData.length === 0 && (
        <p className="py-8 text-center text-slate-400 dark:text-slate-500">Sin puntos de equity</p>
      )}
      {chartError && (
        <p className="py-4 text-center text-sm text-rose-600 dark:text-rose-400">
          Error al renderizar la curva: {chartError}
        </p>
      )}
    </div>
  );
}
