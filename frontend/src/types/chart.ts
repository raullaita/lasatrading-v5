import type { PatternChartMarker } from "./patterns";

/**
 * Tipos del grafico unificado. Espejo de `ChartDataOut` en
 * `app/modules/patterns/schemas.py`.
 *
 * A diferencia de los demas modulos, aqui los OHLCV son `number` y no string:
 * lightweight-charts los quiere numericos y el explorador tendria que convertir
 * en cada serie. El unico `Decimal` que cruza la frontera es el `volume`, que
 * no se pinta pero llega en la respuesta.
 */

/** Una vela del grafico. */
export interface ChartCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Punto de una serie de indicador superpuesta. */
export interface ChartIndicatorPoint {
  timestamp: string;
  value: number;
}

/**
 * Respuesta de `GET /patterns/chart` y de `GET /patterns/scans/{id}/chart`.
 *
 * Los cuatro campos del muestreo existen por una razon concreta: un grafico que
 * enseña 1.500 velas de un rango de 8.760, sin decirlo, se lee como el rango
 * completo. `total_points` son las velas reales del rango y `returned` las que
 * vienen pintadas; `step` es cuantas se saltan entre una pintada y la siguiente.
 *
 * `missing_indicators` no es un campo informativo: es la diferencia entre "este
 * indicador no esta calculado para este rango" y "este indicador no existe en
 * el sistema". Sin el, pedir `EMA_50` en 2022 lo hacia desaparecer en silencio.
 */
export interface ChartData {
  symbol: string;
  timeframe: string;
  date_from?: string | null;
  date_to?: string | null;
  candles: ChartCandle[];
  indicators: Record<string, ChartIndicatorPoint[]>;
  markers: PatternChartMarker[];
  missing_indicators: string[];
  total_points: number;
  returned: number;
  step: number;
  sampled: boolean;
}

/** Un indicador calculado, con la cobertura que tiene de verdad. */
export interface IndicatorAvailability {
  name: string;
  params: Record<string, number | string>;
  date_from: string;
  date_to: string;
  points: number;
}

/** `GET /features/data/indicators`. */
export interface IndicatorAvailabilityList {
  symbol: string;
  timeframe: string;
  indicators: IndicatorAvailability[];
}

/**
 * Parametros de `GET /patterns/chart`.
 *
 * `features` y `patterns` viajan como CSV y no repetidos, a diferencia de los
 * filtros de `/trades`, que si los repiten. Aqui se piden por nombre exacto de
 * serie y el backend hace `.split(",")`; ahi son filtros de tabla y el valor
 * puede contener comas. Mezclar las dos convenciones seria tener que recordar
 * cual aplica en cada llamada.
 */
export interface ChartParams {
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  /** Series a superponer, con los nombres tal cual los calcula el motor. */
  features?: string;
  patterns?: string;
  /** Escaneo cuyas detecciones se marcan. Sin el, no hay markers. */
  scan?: string;
  max_points?: number;
}
