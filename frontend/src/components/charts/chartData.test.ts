import { describe, expect, it } from "vitest";

import {
  type ChartRow,
  colorForIndicator,
  highlightRange,
  timeframeSeconds,
  indicatorNames,
  fromPreviewRows,
  toChartRows,
  toLineData,
  toUnixSeconds,
} from "./chartData";
import type { ChartData } from "../../types/chart";

/**
 * Tests de la logica pura del grafico, sin DOM.
 *
 * Las tres cosas que fallan aqui fallan en silencio, y por eso merecen test:
 * una vela fuera de orden no lanza error, pinta el grafico desordenado; un
 * `NaN` en una serie rompe lightweight-charts entero en vez de dejar un hueco.
 * Ninguno de los dos se ve leyendo el codigo.
 *
 * El filtrado y el orden de los markers **no** se prueban aqui: eso vive en
 * `prepareMarkers` (`patternUtils.test.ts`).
 */

const T0 = "2024-01-01T00:00:00Z";

function candle(index: number, close = 100 + index): ChartData["candles"][number] {
  const iso = toUnixSeconds(T0)! + index * 3600;
  return {
    timestamp: new Date(iso * 1000).toISOString(),
    open: close,
    high: close + 1,
    low: close - 1,
    close,
    volume: 10,
  };
}

function punto(index: number, value: number): ChartData["indicators"][string][number] {
  const iso = toUnixSeconds(T0)! + index * 3600;
  return { timestamp: new Date(iso * 1000).toISOString(), value };
}

describe("toUnixSeconds", () => {
  it("convierte ISO a segundos", () => {
    expect(toUnixSeconds(T0)).toBe(1704067200);
  });

  it("devuelve null en vez de NaN para lo que no parsea", () => {
    expect(toUnixSeconds("no-es-una-fecha")).toBeNull();
  });
});

describe("toChartRows", () => {
  it("fusiona velas e indicadores por marca de tiempo", () => {
    const rows = toChartRows({
      candles: [candle(0), candle(1)],
      indicators: { EMA_20: [punto(0, 99), punto(1, 100)] },
    });

    expect(rows).toHaveLength(2);
    expect(rows[0].indicators.EMA_20).toBe(99);
    expect(rows[1].indicators.EMA_20).toBe(100);
    expect(rows[0].ohlc?.close).toBe(100);
  });

  it("una vela con OHLC no numerico conserva la fila con ohlc nulo", () => {
    const rota = { ...candle(0), close: Number.NaN };
    const rows = toChartRows({ candles: [rota], indicators: {} });

    expect(rows).toHaveLength(1);
    expect(rows[0].ohlc).toBeNull();
  });

  it("descarta las velas cuyo timestamp no parsea en vez de colar NaN", () => {
    const rows = toChartRows({
      candles: [{ ...candle(0), timestamp: "basura" }, candle(1)],
      indicators: {},
    });

    expect(rows).toHaveLength(1);
  });

  it("un indicador con NaN no se cuela en la fila", () => {
    const rows = toChartRows({
      candles: [candle(0)],
      indicators: { RSI_14: [{ timestamp: T0, value: Number.NaN }] },
    });

    expect(rows[0].indicators.RSI_14).toBeUndefined();
  });

  it("no inventa un valor en las velas donde el indicador no tiene punto", () => {
    const rows = toChartRows({
      candles: [candle(0), candle(1), candle(2)],
      indicators: { EMA_20: [punto(1, 50)] },
    });

    expect(Object.keys(rows[0].indicators)).toHaveLength(0);
    expect(rows[1].indicators.EMA_20).toBe(50);
    expect(Object.keys(rows[2].indicators)).toHaveLength(0);
  });
});

describe("indicatorNames", () => {
  it("devuelve los indicadores presentes, sin repetir", () => {
    const rows = toChartRows({
      candles: [candle(0), candle(1)],
      indicators: { EMA_20: [punto(0, 1)], RSI_14: [punto(1, 2)] },
    });

    expect(indicatorNames(rows)).toEqual(["EMA_20", "RSI_14"]);
  });
});

describe("toLineData", () => {
  const rows: ChartRow[] = [
    { seconds: 1, time: 1 as never, ohlc: null, indicators: { A: 1 } },
    { seconds: 2, time: 2 as never, ohlc: null, indicators: {} },
    { seconds: 3, time: 3 as never, ohlc: null, indicators: { A: 3 } },
  ];

  it("deja huecos donde no hay valor, sin rellenar", () => {
    // Rellenar con el ultimo valor conocido seria dibujar una escalera que no
    // existe en los datos: la linea saltaria de 1 a 3 pasando por 1 en el hueco.
    expect(toLineData(rows, "A")).toEqual([
      { time: 1, value: 1 },
      { time: 3, value: 3 },
    ]);
  });

  it("una serie que no existe devuelve lista vacia, no falla", () => {
    expect(toLineData(rows, "INEXISTENTE")).toEqual([]);
  });
});

describe("timeframeSeconds", () => {
  it.each([
    ["1m", 60],
    ["15m", 900],
    ["1h", 3600],
    ["4h", 14400],
    ["1d", 86400],
    ["1w", 604800],
  ])("%s son %i segundos", (tf, esperado) => {
    expect(timeframeSeconds(tf)).toBe(esperado);
  });

  it("un timeframe que no se reconoce cae a 1 minuto", () => {
    // Igual que el resto del proyecto con los datos que no sabe leer: un valor
    // por defecto conocido, no un throw a mitad de un render.
    expect(timeframeSeconds("")).toBe(60);
    expect(timeframeSeconds("diario")).toBe(60);
  });
});

describe("highlightRange", () => {
  it("centra la ventana en la vela indicada", () => {
    const { from, to } = highlightRange(1000, 60);

    expect(from).toBe(1000 - 3600);
    expect(to).toBe(1000 + 3600);
  });

  it("la ventana se mide en velas del timeframe, no en minutos fijos", () => {
    // 60 velas de 1h son 60 horas a cada lado. Con los 60 s fijos de antes
    // quedaban dos velas en pantalla, que no es «entrar a ver la deteccion».
    const { from, to } = highlightRange(1_000_000, 60, timeframeSeconds("1h"));

    expect(from).toBe(1_000_000 - 60 * 3600);
    expect(to).toBe(1_000_000 + 60 * 3600);
  });

  it("el mismo timeframe da la misma ventana", () => {
    expect(highlightRange(0, 60, timeframeSeconds("4h"))).toEqual(
      highlightRange(0, 60, timeframeSeconds("4h")),
    );
  });
});

describe("colorForIndicator", () => {
  it("el mismo nombre da el mismo color siempre", () => {
    // Si el color dependiera de la posicion, EMA_20 seria amber en una pantalla
    // y verde en otra segun el orden de llegada, y el usuario dejaria de
    // confiar en el color.
    expect(colorForIndicator("EMA_20")).toBe(colorForIndicator("EMA_20"));
  });

  it("nombres distintos no comparten color", () => {
    expect(colorForIndicator("EMA_20")).not.toBe(colorForIndicator("RSI_14"));
  });
});

describe("fromPreviewRows", () => {
  it("fusiona las filas por marca de tiempo y las ordena", () => {
    const rows = fromPreviewRows([
      {
        timestamp: new Date((1704067200 + 3600) * 1000).toISOString(),
        open: 2,
        high: 2,
        low: 2,
        close: 2,
        volume: null,
        indicators: { A: 20 },
      },
      { timestamp: T0, open: 1, high: 1, low: 1, close: 1, volume: null, indicators: { A: 10 } },
    ]);

    // Sin ordenar, la serie de lightweight-charts recibe los puntos desordenados.
    expect(rows.map((r) => r.seconds)).toEqual(
      [...rows.map((r) => r.seconds)].sort((a, b) => a - b),
    );
    expect(rows[0].indicators.A).toBe(10);
    expect(rows[1].indicators.A).toBe(20);
  });

  it("acepta una fila con OHLC nulo y otra con el dato", () => {
    const rows = fromPreviewRows([
      {
        timestamp: T0,
        open: null,
        high: null,
        low: null,
        close: null,
        volume: null,
        indicators: { A: 1 },
      },
      { timestamp: T0, open: 5, high: 5, low: 5, close: 5, volume: null, indicators: {} },
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0].ohlc?.close).toBe(5);
  });

  it("conserva la fila aunque el OHLC sea nulo, para no perder el indicador", () => {
    const rows = fromPreviewRows([
      {
        timestamp: T0,
        open: null,
        high: null,
        low: null,
        close: null,
        volume: null,
        indicators: { A: 1 },
      },
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0].ohlc).toBeNull();
    expect(rows[0].indicators.A).toBe(1);
  });

  it("descarta indicadores con NaN", () => {
    const rows = fromPreviewRows([
      {
        timestamp: T0,
        open: 1,
        high: 1,
        low: 1,
        close: 1,
        volume: null,
        indicators: { A: Number.NaN },
      },
    ]);

    expect(Object.keys(rows[0].indicators)).toHaveLength(0);
  });
});
