import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useTheme } from "../../theme/theme";
import { isFiniteNumber, prepareMarkers, toUnixSeconds } from "./patternUtils";
import type {
  PatternChartCandle,
  PatternChartIndicatorPoint,
  PatternChartMarker,
} from "../../types/patterns";

/**
 * Paleta de las series de indicadores. Se mantiene separada de la de Features a
 * proposito: aqui las series son overlays de precio, no paneles aparte, asi que
 * se repiten los mismos siete colores que en `FeatureChart` para que un RSI se
 * reconozca igual en las dos pantallas.
 */
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

/** Velas visibles alrededor de la vela resaltada, por lado. */
const HIGHLIGHT_WINDOW_BARS = 60;

export function PatternChart({
  candles,
  indicators,
  markers,
  symbol,
  timeframe,
  highlightTimestamp,
}: {
  candles: PatternChartCandle[];
  /** Mapa de nombre a serie, tal y como lo devuelve `GET /scans/{id}/chart`. */
  indicators: Record<string, PatternChartIndicatorPoint[]>;
  markers: PatternChartMarker[];
  symbol: string;
  timeframe: string;
  /**
   * Vela a la que hay que llevar la vista. La usa `OccurrenceTable` cuando se
   * pulsa "Ver en gráfico": sin esto, abrir una deteccion de hace tres meses
   * deja el grafico en el extremo derecho del rango y el marker fuera de
   * pantalla.
   */
  highlightTimestamp?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const { theme } = useTheme();

  const candleData = useMemo<CandlestickData[]>(() => {
    const rows: CandlestickData[] = [];
    for (const candle of candles) {
      const seconds = toUnixSeconds(candle.timestamp);
      if (seconds === null) continue;
      if (
        !isFiniteNumber(candle.open) ||
        !isFiniteNumber(candle.high) ||
        !isFiniteNumber(candle.low) ||
        !isFiniteNumber(candle.close)
      ) {
        continue;
      }
      rows.push({
        time: seconds as Time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
    }
    // El backend ya viene ordenado, pero un sort defensivo evita que un cambio
    // futuro en la query rompa el render entero.
    return rows.sort((a, b) => (a.time as number) - (b.time as number));
  }, [candles]);

  const indicatorSeries = useMemo(() => {
    return Object.entries(indicators)
      .map(([name, points]) => {
        const lineData: LineData[] = [];
        for (const point of points as PatternChartIndicatorPoint[]) {
          const seconds = toUnixSeconds(point.timestamp);
          if (seconds === null || !isFiniteNumber(point.value)) continue;
          lineData.push({ time: seconds as Time, value: point.value });
        }
        if (lineData.length === 0) return null;
        return {
          name,
          data: lineData.sort((a, b) => (a.time as number) - (b.time as number)),
        };
      })
      .filter((entry): entry is { name: string; data: LineData[] } => entry !== null);
  }, [indicators]);

  const plottable = candleData.length > 0 || indicatorSeries.length > 0;

  const highlightSeconds = useMemo(
    () => (highlightTimestamp ? toUnixSeconds(highlightTimestamp) : null),
    [highlightTimestamp],
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

      // Se guarda la referencia de la serie de velas: `setMarkers` va sobre la
      // serie, no sobre el chart, y sin esta referencia no se podrian pintar.
      let candleSeries: ISeriesApi<"Candlestick"> | null = null;
      if (candleData.length > 0) {
        candleSeries = api.addCandlestickSeries();
        candleSeries.setData(candleData);
      }

      const candleSeconds = new Set(candleData.map((c) => c.time as number));
      const prepared = prepareMarkers(markers, candleSeconds);
      if (candleSeries && prepared.length > 0) {
        // Orden ascendente obligatorio: ver `prepareMarkers`.
        candleSeries.setMarkers(prepared);
      }

      indicatorSeries.forEach((entry, colorIdx) => {
        const series = api.addLineSeries({
          color: INDICATOR_COLORS[colorIdx % INDICATOR_COLORS.length],
          lineWidth: 1,
          title: entry.name,
        });
        series.setData(entry.data);
      });

      if (highlightSeconds !== null && candleSeconds.has(highlightSeconds)) {
        // `setVisibleRange` y no `scrollToPosition`: este ultimo desplaza la
        // barra de scroll pero deja el zoom como estuviera, y con el rango
        // completo de un año la vela queda microscópica. Fijando una ventana
        // de velas a cada lado se ve el contexto sin perder el detalle.
        const from = highlightSeconds - HIGHLIGHT_WINDOW_BARS * 60;
        const to = highlightSeconds + HIGHLIGHT_WINDOW_BARS * 60;
        try {
          api.timeScale().setVisibleRange({ from: from as Time, to: to as Time });
        } catch {
          // Fuera del rango de datos: mejor un fitContent que un chart en blanco.
          api.timeScale().fitContent();
        }
      } else {
        api.timeScale().fitContent();
      }

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
      setChartError(err instanceof Error ? err.message : "No se pudo renderizar el gráfico.");
      return;
    }

    return () => {
      resizeObserver?.disconnect();
      chart?.remove();
      chartRef.current = null;
    };
  }, [candleData, indicatorSeries, markers, plottable, symbol, timeframe, theme, highlightSeconds]);

  const markerCount = useMemo(() => {
    const candleSeconds = new Set(candleData.map((c) => c.time as number));
    return prepareMarkers(markers, candleSeconds).length;
  }, [candleData, markers]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
          {symbol} · {timeframe} — Velas con detecciones
        </h3>
        {markerCount > 0 && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {markerCount} {markerCount === 1 ? "detección" : "detecciones"}
          </span>
        )}
      </div>
      <div ref={containerRef} className="w-full" />
      {candles.length === 0 && indicatorSeries.length === 0 && (
        <p className="py-8 text-center text-slate-400 dark:text-slate-500">
          Sin velas para graficar
        </p>
      )}
      {candles.length > 0 && !plottable && (
        <p className="py-8 text-center text-sm text-amber-600 dark:text-amber-400">
          Se recibieron {candles.length} velas, pero ninguna contiene valores numéricos válidos para
          graficar.
        </p>
      )}
      {plottable && chartError && (
        <p className="py-4 text-center text-sm text-rose-600 dark:text-rose-400">
          Error al renderizar el gráfico: {chartError}
        </p>
      )}
      {plottable && !chartError && (
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
          Las detecciones del rango visible están marcadas sobre las velas. Usa «Ver en gráfico» en
          la tabla de ocurrencias para saltar a una concreta.
        </p>
      )}
    </div>
  );
}
