import type { LineData, Time } from "lightweight-charts";

import type { ChartCandle, ChartData, ChartIndicatorPoint } from "../../types/chart";
import type { FeaturePreviewRow } from "../../types/features";

/**
 * Logica pura del grafico unificado, separada del componente.
 *
 * Vive aqui y no en `UnifiedChart.tsx` por el motivo que ya funciona en el
 * proyecto con `patternUtils.ts`: eslint (`react-refresh/only-export-components`)
 * avisa cuando un archivo de componente exporta algo mas que componentes, y el
 * resultado es que el HMR deja de funcionar para ese archivo en desarrollo.
 *
 * Y sobre todo porque asi se puede **probar sin DOM**. Las tres cosas que
 * fallan aqui fallan en silencio: una vela con el timestamp mal ordenado no
 * lanza error, pinta las velas desordenadas; un indicador con un `NaN` metido
 * rompe la libreria entera en vez de dejar un hueco; y una serie de markers sin
 * el orden ascendente que exige `setMarkers` no se pinta y no dice nada.
 */

/**
 * Fila fusionada: una vela y, en la misma marca de tiempo, los valores de los
 * indicadores que existen ahi.
 *
 * Es la forma que necesita el explorador (una consulta junta velas y features y
 * hay que unirlas por tiempo) y la que produce el backend en
 * `GET /patterns/chart`. La ruta de escaneo devuelve velas e indicadores por
 * separado y `toChartRows` los convierte.
 */
export interface ChartRow {
  seconds: number;
  time: Time;
  ohlc: {
    time: Time;
    open: number;
    high: number;
    low: number;
    close: number;
  } | null;
  indicators: Record<string, number>;
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * De ISO 8601 a segundos Unix, que es la unidad de tiempo que espera
 * lightweight-charts. Devuelve `null` para lo que no parsea, en vez de `NaN`:
 * un `NaN` en la serie rompe la libreria entera, mientras que saltarse la vela
 * solo deja un hueco.
 */
export function toUnixSeconds(iso: string): number | null {
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

/**
 * Convierte la respuesta del backend en filas fusionadas.
 *
 * El backend ya devuelve las velas y los indicadores **alineados**: los
 * indicadores vienen recortados a las mismas marcas de tiempo de las velas que
 * se envian, porque el muestreo los filtra por `only_timestamps`. Aqui no se
 * une nada: se recorre cada vela y se copia el valor de cada indicador en esa
 * fila. Unir por tiempo aqui seria redundante y, si algun dia el backend
 * devolviera un indicador desalineado, lo ocultaria en vez de detectarlo.
 */
export function toChartRows(data: Pick<ChartData, "candles" | "indicators">): ChartRow[] {
  const rows: ChartRow[] = [];
  for (const candle of data.candles) {
    const seconds = toUnixSeconds(candle.timestamp);
    if (seconds === null) continue;
    const ohlc = isUsableOhlc(candle) ? ohlcOf(candle, seconds as Time) : null;
    const indicators: Record<string, number> = {};
    for (const [name, points] of Object.entries(data.indicators)) {
      const value = valueAt(points, seconds);
      if (value !== null) indicators[name] = value;
    }
    rows.push({ seconds, time: seconds as Time, ohlc, indicators });
  }
  return rows;
}

function isUsableOhlc(candle: ChartCandle): boolean {
  return (
    isFiniteNumber(candle.open) &&
    isFiniteNumber(candle.high) &&
    isFiniteNumber(candle.low) &&
    isFiniteNumber(candle.close)
  );
}

function ohlcOf(candle: ChartCandle, time: Time) {
  return {
    time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  };
}

/** Valor de un indicador en un instante dado, o `null` si no lo hay ahi. */
function valueAt(points: ChartIndicatorPoint[], seconds: number): number | null {
  const punto = points.find((p) => toUnixSeconds(p.timestamp) === seconds);
  if (!punto) return null;
  return isFiniteNumber(punto.value) ? punto.value : null;
}

/** Nombres de indicador presentes en las filas, en el orden en que aparecen. */
export function indicatorNames(rows: ChartRow[]): string[] {
  const names: string[] = [];
  for (const row of rows) {
    for (const name of Object.keys(row.indicators)) {
      if (!names.includes(name)) names.push(name);
    }
  }
  return names;
}

/**
 * Serie de una linea lista para `setData`.
 *
 * Los huecos (una fila sin ese indicador) **no** se rellenan: lightweight-charts
 * une los puntos por tiempo y dibuja la linea a traves, que es lo correcto para
 * un indicador. Rellenar con el ultimo valor conocido seria_draw_ una escalera
 * que no existe en los datos.
 */
export function toLineData(rows: ChartRow[], name: string): LineData[] {
  const points: LineData[] = [];
  for (const row of rows) {
    const value = row.indicators[name];
    if (isFiniteNumber(value)) points.push({ time: row.time, value });
  }
  return points;
}

/**
 * Segundos que dura una vela del timeframe dado.
 *
 * Existe porque `highlightRange` multiplicaba por 60 fijos: el numero era una
 * ventana de **minutos**, no de velas, y eso solo es verdad en velas de 1
 * minuto. En un grafico de 1h «60» encuadraba dos velas, y en uno de 1d el
 *Recentrar no llegaba ni a la vela entera. El numero de velas wanted es
 * «cuantas velas de contexto ver», y para pasarlo a segundos hay que saber
 * cuanto dura una vela aqui.
 *
 * Un timeframe que no se reconoce cae a 1 minuto, que es lo que hacen el resto
 * de pantallas del proyecto con los datos que no saben leer.
 */
export function timeframeSeconds(timeframe: string): number {
  const partes = /^(\d+)([mhdw])$/.exec(timeframe.trim());
  if (!partes) return 60;
  const cantidad = Number(partes[1]);
  switch (partes[2]) {
    case "m":
      return cantidad * 60;
    case "h":
      return cantidad * 3600;
    case "d":
      return cantidad * 86400;
    default:
      return cantidad * 604800;
  }
}

/**
 * Ventana de tiempo centrada en una vela, en unidades de lightweight-charts.
 *
 * `candlesShown` es el numero de **velas** de contexto a cada lado, y
 * `candleSeconds` lo que dura una vela en este grafico. El parametro segundo es
 * opcional para no romper a quien llame con dos argumentos, pero el sitio que
 * importa, `UnifiedChart`, lo pasa siempre: sin el, la ventana depende de que
 * el timeframe sea de un minuto.
 */
export function highlightRange(
  highlightSeconds: number,
  candlesShown: number,
  candleSeconds = 60,
): { from: Time; to: Time } {
  const window = candlesShown * candleSeconds;
  return {
    from: (highlightSeconds - window) as Time,
    to: (highlightSeconds + window) as Time,
  };
}

const PALETTE = ["#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

/**
 * Color estable de un indicador.
 *
 * Estable **por nombre**, no por orden de llegada: si el mismo `EMA_20` sale
 * amber en una pantalla y verde en otra porquellego en otro momento, el usuario
 * deja de confiar en el color. Con mas de siete indicadores se repite, y a
 * partir de ahi el color ya no identifica a la serie: es el titulo el que
 * identifica.
 */
export function colorForIndicator(name: string): string {
  const hash = name.split("").reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0, 7);
  return PALETTE[hash % PALETTE.length];
}

export const CHART_THEME = {
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
 * Adaptador del preview de un job de features a filas del grafico.
 *
 * Es el segundo formato que hay que entender: `GET /jobs/{id}/preview` devuelve
 * las filas **ya fusionadas** y con el OHLC en `number | null`, mientras que
 * `GET /patterns/chart` devuelve las velas aparte de los indicadores. El merge
 * por marca de tiempo lo hacia `FeatureChart` dentro del componente, sin un solo
 * test, y aqui se hace en una funcion pura que se puede probar.
 *
 * Con filas duplicadas en la misma marca de tiempo gana la primera que trae el
 * OHLC. No deberia pasar (la clave primaria del preview es el timestamp), pero
 * un `Map` sin esa preferencia se quedaria con la ultima y dejaria la vela en
 * `null` sin decir nada.
 */
export function fromPreviewRows(rows: FeaturePreviewRow[]): ChartRow[] {
  const porInstante = new Map<number, ChartRow>();

  for (const row of rows) {
    const seconds = toUnixSeconds(row.timestamp);
    if (seconds === null) continue;

    let destino = porInstante.get(seconds);
    if (!destino) {
      destino = { seconds, time: seconds as Time, ohlc: null, indicators: {} };
      porInstante.set(seconds, destino);
    }

    if (
      destino.ohlc === null &&
      isFiniteNumber(row.open) &&
      isFiniteNumber(row.high) &&
      isFiniteNumber(row.low) &&
      isFiniteNumber(row.close)
    ) {
      destino.ohlc = {
        time: destino.time,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
      };
    }

    for (const [name, value] of Object.entries(row.indicators)) {
      if (isFiniteNumber(value)) destino.indicators[name] = value;
    }
  }

  return Array.from(porInstante.values()).sort((a, b) => a.seconds - b.seconds);
}
