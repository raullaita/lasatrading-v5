import type { LineData } from "lightweight-charts";

import { type ChartRow, colorForIndicator, toLineData } from "./chartData";

/**
 * Sincroniza las series de indicadores con las que el grafico tiene abiertas.
 *
 * Vive fuera del componente, y no por gusto, sino por la razon que ya funciona
 * en el proyecto: asi se puede **probar sin DOM**. El invariante que hay que
 * proteger —que marcar un indicador no puede reconstruir el chart— no se
 * comprueba leyendo un `useEffect`: hay que poder contarlo.
 *
 * Por eso las interfaces son **estructurales** y no los tipos de
 * lightweight-charts. `IChartApi` exige un DOM para instanciarse, asi que un
 * test con el tipo real no podria construir nada; con estas interfaces un doble
 * de cuatro metodos verifica el comportamiento completo.
 *
 * La regla que implementa: las series se identifican **por nombre**, nunca por
 * posicion. Si al desmarcar un indicador se eliminara la serie por indice, las
 * demas se permutarian y `EMA_20` se quedaria con los datos de `RSI_14`.
 */
export interface LineHandle {
  setData(data: LineData[]): void;
}

/**
 * Opciones de la serie, **todas opcionales a proposito**.
 *
 * `IChartApi.addLineSeries` recibe un `DeepPartial`, asi que si esta interfaz
 * exigiera un objeto completo, el chart real no seria asignable a `SeriesHost` y
 * habria que meter un `as` en el componente. Las opciones van sueltas para que
 * el unico sitio que las rellena sea `syncIndicatorSeries`.
 */
export interface LineSeriesOptions {
  color?: string;
  lineWidth?: number;
  title?: string;
}

export interface SeriesHost {
  addLineSeries(options?: LineSeriesOptions): LineHandle;
  removeSeries(series: LineHandle): void;
}

export function syncIndicatorSeries(
  chart: SeriesHost,
  rows: ChartRow[],
  names: string[],
  existing: Map<string, LineHandle>,
): Map<string, LineHandle> {
  const vivas = new Map(existing);

  for (const name of [...vivas.keys()]) {
    if (!names.includes(name)) {
      chart.removeSeries(vivas.get(name)!);
      vivas.delete(name);
    }
  }

  for (const name of names) {
    const data = toLineData(rows, name);
    // Un indicador pedido sin un solo punto no abre serie. Se distingue de "no
    // pedido" en que la respuesta del backend trae `missing_indicators`, y esa
    // diferencia la pinta la pagina, no el grafico.
    if (data.length === 0) continue;
    let serie = vivas.get(name);
    if (!serie) {
      serie = chart.addLineSeries({
        color: colorForIndicator(name),
        lineWidth: 1,
        title: name,
      });
      vivas.set(name, serie);
    }
    serie.setData(data);
  }

  return vivas;
}
