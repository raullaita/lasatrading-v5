import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";

import { toUnixSeconds } from "../Patterns/patternUtils";
import { useTheme } from "../../theme/theme";
import type { WalkForwardEquityPoint } from "../../types/walkForward";
import { toNumber } from "../../utils/format";

const THEME_COLORS = {
  light: {
    background: "#ffffff",
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
 * Curva OOS encadenada frente al benchmark encadenado.
 *
 * Dos series de lineas sobre el tiempo, con lightweight-charts y no SVG a mano
 * como `ExcursionChart`. La razon de alla no aplica aqui: `ExcursionChart` es
 * un histograma sobre un eje de porcentaje, y SVG a mano era lo indicado porque
 * lightweight-charts no tiene barras. Esto es una serie temporal con zoom y
 * arrastre, que es justo lo que la libreria hace bien y lo que un SVG a mano
 * habria que reimplementar. Sin dependencia nueva, que es lo que
 * pedia la §9.
 *
 * **Las dos series son la misma medida del informe**: la estrategia encadenada y
 * el mercado encadenado con el capital rebasado en cada frontera de ventana.
 * Comparar la estrategia encadenada contra un mercado que no lo esta daria una
 * diferencia que no existe, y por eso el backend los guarda en la misma fila.
 *
 * El capital arranca en 1 y ambas series se normalizan por su primer valor, para
 * que se pueda comparar la forma de las dos y no su escala absoluta, que depende
 * del capital inicial. Los valores absolutos estan en las tarjetas de arriba.
 */
export function OosEquityChart({
  points,
  height = 300,
}: {
  points: WalkForwardEquityPoint[];
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const equityRef = useRef<ISeriesApi<"Line"> | null>(null);
  const marketRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const { theme } = useTheme();

  const { equityData, marketData } = useMemo(() => {
    const strategy: LineData[] = [];
    const market: LineData[] = [];
    // Se normaliza por el primer valor, y no por `initial_capital`: con un
    // capital inicial de 1.000 la curva empieza en 1.000 y la comparacion con el
    // mercado es la misma, pero normalizar aqui hace que el grafico siga siendo
    // legible aunque el backend deje de mandar ese campo.
    const base = toNumber(points[0]?.equity);
    const marketBase = toNumber(points[0]?.market_equity);
    if (base === null || marketBase === null || base === 0 || marketBase === 0) {
      return { equityData: strategy, marketData: market };
    }
    for (const point of points) {
      const seconds = toUnixSeconds(point.timestamp);
      const equity = toNumber(point.equity);
      const marketEquity = toNumber(point.market_equity);
      if (equity === null || marketEquity === null) continue;
      strategy.push({ time: seconds as Time, value: equity / base });
      market.push({ time: seconds as Time, value: marketEquity / marketBase });
    }
    return { equityData: strategy, marketData: market };
  }, [points]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let chart: IChartApi;
    try {
      const colors = THEME_COLORS[theme];
      chart = createChart(container, {
        width: container.clientWidth,
        height,
        layout: { background: { color: colors.background }, textColor: colors.text },
        grid: {
          vertLines: { color: colors.grid },
          horzLines: { color: colors.grid },
        },
        rightPriceScale: { borderColor: colors.border },
        timeScale: { borderColor: colors.border },
        localization: {
          // El eje es tiempo real de velas, no fechas de sesion: un dia entero
          // entre dos velas a 1h es un hueco, no un mercado cerrado.
          timeFormatter: (time: Time) => String(time),
        },
      });
      const equity = chart.addLineSeries({
        color: "#2563eb",
        lineWidth: 2,
        priceLineVisible: false,
        title: "Estrategia OOS",
      });
      const market = chart.addLineSeries({
        color: "#94a3b8",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        title: "Mercado OOS",
      });
      chartRef.current = chart;
      equityRef.current = equity;
      marketRef.current = market;
      setChartError(null);
    } catch (error) {
      setChartError(error instanceof Error ? error.message : String(error));
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) chart.applyOptions({ width });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      equityRef.current = null;
      marketRef.current = null;
    };
  }, [theme, height]);

  useEffect(() => {
    equityRef.current?.setData(equityData);
    marketRef.current?.setData(marketData);
  }, [equityData, marketData]);

  if (chartError) {
    return (
      <div
        className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        role="alert"
      >
        No se pudo dibujar la curva: {chartError}
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="rounded border border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Este walk-forward no tiene curva que enseñar.
      </div>
    );
  }

  return <div ref={containerRef} className="w-full" />;
}
