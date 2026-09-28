import { describe, expect, it } from "vitest";

import { type ChartRow, toChartRows } from "./chartData";
import { type LineHandle, type SeriesHost, syncIndicatorSeries } from "./chartSeries";
import type { ChartData } from "../../types/chart";

/**
 * Tests de la sincronizacion de series, con un doble de la libreria.
 *
 * Aqui vive el invariante que la spec marca como obligatorio: **marcar o
 * desmarcar un indicador no puede reconstruir el grafico**. En los componentes
 * anteriores (`FeatureChart` y `PatternChart`) cada cambio de props hacia un
 * `chart.remove()` y un `createChart()` nuevo, con el parpadeo y los ~200 ms que
 * eso cuesta, y no habia forma de comprobarlo porque la logica estaba dentro de
 * un `useEffect` que necesita un DOM.
 *
 * El doble tiene cuatro metodos y cuenta llamadas, que es lo que hace posible
 * la afirmacion: no se comprueba que "no se haya roto nada", se comprueba que
 * `addLineSeries` se ha llamado tres veces y que ninguna serie existente se ha
 * vuelto a crear.
 */
class ChartFalso implements SeriesHost {
  readonly creadas: string[] = [];
  readonly eliminadas: LineHandle[] = [];
  readonly Writes: Map<LineHandle, number> = new Map();
  private contador = 0;

  addLineSeries(options: { title: string }): LineHandle {
    this.creadas.push(options.title);
    const id = ++this.contador;
    const handle: LineHandle = {
      setData: () => {
        this.Writes.set(handle, (this.Writes.get(handle) ?? 0) + 1);
      },
    };
    Object.defineProperty(handle, "id", { value: id });
    return handle;
  }

  removeSeries(serie: LineHandle): void {
    this.eliminadas.push(serie);
  }

  vecesEscrita(serie: LineHandle): number {
    return this.Writes.get(serie) ?? 0;
  }
}

function filas(indicadores: Record<string, number[]>): ChartRow[] {
  const total = Math.max(...Object.values(indicadores).map((v) => v.length), 1);
  const data: Pick<ChartData, "candles" | "indicators"> = {
    candles: Array.from({ length: total }, (_, i) => ({
      timestamp: new Date((1704067200 + i * 3600) * 1000).toISOString(),
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 1,
    })),
    indicators: Object.fromEntries(
      Object.entries(indicadores).map(([name, values]) => [
        name,
        values.map((value, i) => ({
          timestamp: new Date((1704067200 + i * 3600) * 1000).toISOString(),
          value,
        })),
      ]),
    ),
  };
  return toChartRows(data);
}

describe("syncIndicatorSeries", () => {
  it("abre una serie por indicador la primera vez", () => {
    const chart = new ChartFalso();

    const vivas = syncIndicatorSeries(
      chart,
      filas({ EMA_20: [1, 2], RSI_14: [3, 4] }),
      ["EMA_20", "RSI_14"],
      new Map(),
    );

    expect(chart.creadas).toEqual(["EMA_20", "RSI_14"]);
    expect([...vivas.keys()]).toEqual(["EMA_20", "RSI_14"]);
  });

  it("NO crea series nuevas al actualizar los datos de las existentes", () => {
    // Este es el invariante. Si aqui apareciera una llamada a `addLineSeries`, el
    // componente estaria reconstruyendo el grafico en cada cambio de props, que
    // es exactamente el defecto que corrige la Tarea 3.5.
    const chart = new ChartFalso();
    const primera = filas({ EMA_20: [1, 2] });
    const vivas = syncIndicatorSeries(chart, primera, ["EMA_20"], new Map());

    const segunda = filas({ EMA_20: [3, 4, 5] });
    syncIndicatorSeries(chart, segunda, ["EMA_20"], vivas);

    expect(chart.creadas).toEqual(["EMA_20"]);
    expect(chart.vecesEscrita(vivas.get("EMA_20")!)).toBe(2);
    expect(chart.eliminadas).toEqual([]);
  });

  it("desmarcar un indicador elimina solo esa serie", () => {
    const chart = new ChartFalso();
    const vivas = syncIndicatorSeries(
      chart,
      filas({ EMA_20: [1], RSI_14: [2] }),
      ["EMA_20", "RSI_14"],
      new Map(),
    );
    const ema = vivas.get("EMA_20")!;

    const tras = syncIndicatorSeries(chart, filas({ RSI_14: [2] }), ["RSI_14"], vivas);

    expect(chart.eliminadas).toEqual([ema]);
    expect([...tras.keys()]).toEqual(["RSI_14"]);
  });

  it("las series se identifican por nombre, no por posicion", () => {
    // Si al desmarcar uno se eliminara por indice, las demas se permutarian y
    // `EMA_20` se quedaria con los datos de `RSI_14`, sin que nada fallara.
    const chart = new ChartFalso();
    const vivas = syncIndicatorSeries(chart, filas({ A: [1], B: [2] }), ["A", "B"], new Map());
    const serieA = vivas.get("A")!;
    const serieB = vivas.get("B")!;

    const tras = syncIndicatorSeries(chart, filas({ B: [2] }), ["B"], vivas);

    expect(tras.get("B")).toBe(serieB);
    expect(chart.eliminadas).toEqual([serieA]);
  });

  it("un indicador sin ningun punto no abre serie", () => {
    const chart = new ChartFalso();

    const vivas = syncIndicatorSeries(
      chart,
      filas({ EMA_20: [1] }),
      ["EMA_20", "VACIA"],
      new Map(),
    );

    expect(chart.creadas).toEqual(["EMA_20"]);
    expect(vivas.has("VACIA")).toBe(false);
  });

  it("sin indicadores cierra todas las series abiertas", () => {
    const chart = new ChartFalso();
    const vivas = syncIndicatorSeries(
      chart,
      filas({ EMA_20: [1], RSI_14: [2] }),
      ["EMA_20", "RSI_14"],
      new Map(),
    );

    const tras = syncIndicatorSeries(chart, filas({}), [], vivas);

    expect(chart.eliminadas).toHaveLength(2);
    expect(tras.size).toBe(0);
  });

  it("sin filas no abre nada", () => {
    const chart = new ChartFalso();

    const vivas = syncIndicatorSeries(chart, [], ["EMA_20"], new Map());

    expect(chart.creadas).toEqual([]);
    expect(vivas.size).toBe(0);
  });
});
