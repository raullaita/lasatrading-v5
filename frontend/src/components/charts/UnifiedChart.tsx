import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";

import { useTheme } from "../../theme/theme";
import { prepareMarkers } from "../Patterns/patternUtils";
import type { PatternChartMarker } from "../../types/patterns";
import {
  type ChartRow,
  CHART_THEME,
  highlightRange,
  timeframeSeconds,
  indicatorNames,
  toUnixSeconds,
} from "./chartData";
import { type LineHandle, syncIndicatorSeries } from "./chartSeries";

/**
 * Grafico de velas con indicadores superpuestos y detecciones marcadas.
 *
 * Unifica `FeatureChart` y `PatternChart`, que eran el mismo componente escrito
 * dos veces: mismos colores de tema, misma paleta de indicadores, mismo
 * `createChart` con las mismas opciones, mismo `ResizeObserver`, mismo
 * `try/catch` y mismo bloque de unas 60 lineas. Lo que se mantiene de cada uno es
 * lo que de verdad aportaba: del segundo, los markers y el centrado en una vela.
 *
 * **La separacion que mas importa: la vida del chart y la vida de los datos.**
 * El chart se crea en un efecto que solo depende del tema, y los `setData` van
 * en efectos separados. En los componentes anteriores, `symbol` y `timeframe`
 * estaban en las dependencias del efecto de creacion aunque solo se usaran
 * como texto de la cabecera, y como las filas se memorizaban sobre las props,
 * cualquier array nuevo hacia un teardown y una reconstruccion completa. Marcar
 * un indicador rehacia el grafico entero: un parpadeo y ~200 ms por clic.
 *
 * lightweight-charts no admite reutilizar una instancia tras `remove()`, asi
 * que hay un chart por montaje y nunca se recicla.
 */
export function UnifiedChart({
  rows,
  markers = [],
  highlightTimestamp,
  title,
  subtitle,
  timeframe,
  height = 420,
}: {
  rows: ChartRow[];
  markers?: PatternChartMarker[];
  /** Lleva la vista a esta vela con una ventana de velas alrededor. */
  highlightTimestamp?: string | null;
  title: string;
  subtitle?: string;
  /**
   * Solo lo usa el Recentrar, y por eso es opcional: sin el, la ventana de
   * contexto se mide en minutos y solo es correcta en velas de 1 minuto.
   */
  timeframe?: string;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineSeriesRef = useRef<Map<string, LineHandle>>(new Map());
  const [chartError, setChartError] = useState<string | null>(null);
  const { theme } = useTheme();

  const nombres = useMemo(() => indicatorNames(rows), [rows]);
  const plottable = rows.some((row) => row.ohlc !== null) || nombres.length > 0;

  // 1 · Crear el chart. Solo depende del tema y del alto: cambiar los datos no
  // llega aqui, y por eso no reconstruye nada.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const colors = CHART_THEME[theme];
    let chart: IChartApi | null = null;
    let resizeObserver: ResizeObserver | null = null;

    try {
      const api: IChartApi = createChart(container, {
        layout: { background: { color: colors.background }, textColor: colors.text },
        grid: {
          vertLines: { color: colors.grid },
          horzLines: { color: colors.grid },
        },
        rightPriceScale: { borderColor: colors.border },
        timeScale: { borderColor: colors.border },
        width: container.clientWidth,
        height,
      });
      chart = api;
      candleSeriesRef.current = api.addCandlestickSeries();
      lineSeriesRef.current = new Map();
      chartRef.current = api;
      setChartError(null);

      resizeObserver = new ResizeObserver(() => {
        const actual = containerRef.current;
        if (actual && chartRef.current) {
          chartRef.current.applyOptions({ width: actual.clientWidth });
        }
      });
      resizeObserver.observe(container);
    } catch (error) {
      if (chart) chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      lineSeriesRef.current = new Map();
      setChartError(error instanceof Error ? error.message : "No se pudo renderizar el gráfico.");
      return;
    }

    return () => {
      resizeObserver?.disconnect();
      chart?.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      lineSeriesRef.current = new Map();
    };
  }, [theme, height]);

  // 2 · Velas. `setData` sobre la serie existente.
  useEffect(() => {
    const serie = candleSeriesRef.current;
    if (!serie) return;
    const data = rows.flatMap((row) => (row.ohlc ? [row.ohlc] : []));
    serie.setData(data);
  }, [rows]);

  // 3 · Indicadores. La sincronizacion vive en `chartSeries` y esta probada con
  // un doble de la libreria: marcar o desmarcar no puede reconstruir el chart, y
  // eso se comprueba contando llamadas a `addLineSeries`, no leyendo este
  // efecto.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    lineSeriesRef.current = syncIndicatorSeries(chart, rows, nombres, lineSeriesRef.current);
  }, [nombres, rows]);

  // 4 · Markers. `setMarkers` va sobre la **serie** de velas, no sobre el
  // chart, y sin la referencia no se podrian pintar.
  const prepared = useMemo(() => {
    const instantes = new Set(rows.map((row) => row.seconds));
    return prepareMarkers(markers, instantes);
  }, [markers, rows]);
  const markerCount = prepared.length;
  useEffect(() => {
    candleSeriesRef.current?.setMarkers(prepared);
  }, [prepared]);

  // 5 · Encuadre. Al Highlight se le fija una ventana de velas en vez de
  // `fitContent`: con el rango de un año entero la vela queda microscopica.
  // La ventana se mide en velas del propio timeframe, que es lo unico que
  // hace que «recentrar» signifique lo mismo en 15m que en 1d.
  const highlightSeconds = useMemo(
    () => (highlightTimestamp ? toUnixSeconds(highlightTimestamp) : null),
    [highlightTimestamp],
  );
  const candleSeconds = useMemo(
    () => (timeframe ? timeframeSeconds(timeframe) : 60),
    [timeframe],
  );
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || rows.length === 0) return;
    if (highlightSeconds === null) {
      chart.timeScale().fitContent();
      return;
    }
    try {
      chart.timeScale().setVisibleRange(
        highlightRange(highlightSeconds, 60, candleSeconds) as {
          from: Time;
          to: Time;
        },
      );
    } catch {
      // Fuera del rango de datos: mejor un fitContent que un grafico en blanco.
      chart.timeScale().fitContent();
    }
    // Sin el `catch` que envuelve a `fitContent` tambien, un rango degenerado
    // (una sola vela) deja la escala sin dominio y lightweight-charts lanza.
  }, [rows, highlightSeconds, candleSeconds]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
        </div>
        {markerCount > 0 && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {markerCount} {markerCount === 1 ? "detección" : "detecciones"}
          </span>
        )}
      </div>

      <div ref={containerRef} className="w-full" />

      {rows.length === 0 && (
        <p className="py-8 text-center text-sm text-slate-400 dark:text-slate-500">
          Sin velas en este rango
        </p>
      )}
      {rows.length > 0 && !plottable && (
        <p className="py-8 text-center text-sm text-amber-600 dark:text-amber-400">
          Se recibieron {rows.length} filas, pero ninguna contiene valores válidos para graficar.
        </p>
      )}
      {plottable && chartError && (
        <p className="py-4 text-center text-sm text-rose-600 dark:text-rose-400">
          Error al renderizar el gráfico: {chartError}
        </p>
      )}
      {plottable && !chartError && markers.length > markerCount && (
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
          {markers.length - markerCount} detecciones caen fuera de las velas mostradas y no se
          pueden marcar: el backend devuelve los markers del rango completo, no solo los del tramo
          muestreado.
        </p>
      )}
    </div>
  );
}
