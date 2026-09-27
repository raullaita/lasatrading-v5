import type { SeriesMarker, Time } from "lightweight-charts";
import type {
  OccurrenceSummary,
  PatternChartMarker,
  PatternDefinition,
  PatternOccurrence,
  PatternSelection,
} from "../../types/patterns";

/**
 * Utilidades compartidas por los componentes de patrones.
 *
 * Viven aquí y no en `PatternSelector.tsx` porque eslint
 * (`react-refresh/only-export-components`) avisa cuando un archivo de componente
 * exporta algo más que componentes: el resultado es que el HMR deja de
 * funcionar para ese archivo en desarrollo. Es una función pura, no un
 * componente, así que no le corresponde estar ahí.
 */

/**
 * Features que faltan para poder ejecutar los patrones seleccionados.
 *
 * Se cruza `PatternDefinition.required_features` del catálogo contra los
 * `indicators` que devuelve `getAvailableData()`. Existe para avisar *antes* de
 * encolar: sin `EMA_50`, un `MA_CROSS_BULLISH` va a fallar seguro con
 * `MissingFeaturesError` en el worker, y descubrirlo leyendo los logs del job
 * es una forma mala de enterarse de que el selector de datos no está completo.
 *
 * Devuelve la lista ordenada y sin duplicados, lista para pintar como aviso.
 */
export function missingFeatures(
  patterns: PatternSelection[],
  catalog: PatternDefinition[],
  availableIndicators: string[],
): string[] {
  const byCode = new Map(catalog.map((d) => [d.code, d]));
  const have = new Set(availableIndicators);
  const missing = new Set<string>();

  for (const selection of patterns) {
    const definition = byCode.get(selection.code);
    if (!definition) continue;
    for (const feature of definition.required_features) {
      if (!have.has(feature)) missing.add(feature);
    }
  }

  return Array.from(missing).sort();
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
 * Resumen de un conjunto de ocurrencias ya traidas al cliente.
 *
 * Existe porque `GET /occurrences/summary` no acepta `job_id`, así que no hay
 * forma de pedirle al servidor el desglose de un escaneo concreto. Los dos
 * usos son distintos y por eso hay que saber de dónde sale cada número:
 *
 * - En la tabla global de `Occurrences` el resumen viene del backend y cubre
 *   todo el conjunto filtrado, no solo la página visible.
 * - En el detalle de un escaneo este resumen cubre **solo las ocurrencias
 *   cargadas**. La interfaz lo dice, en vez de presentar un total parcial como
 *   si fuera el completo.
 *
 * Es el mismo cálculo que hace `PatternScanService.get_occurrences_summary`,
 * sobre arrays en vez de SQL.
 */
export function summarizeOccurrences(occurrences: PatternOccurrence[]): OccurrenceSummary {
  const byPattern = new Map<string, { count: number; bullish: number; bearish: number }>();
  const bySymbol = new Map<string, number>();
  const byTimeframe = new Map<string, number>();
  let bullish = 0;
  let bearish = 0;
  let first: string | null = null;
  let last: string | null = null;

  for (const occurrence of occurrences) {
    const code = occurrence.pattern_name;
    const bucket = byPattern.get(code) ?? { count: 0, bullish: 0, bearish: 0 };
    bucket.count += 1;
    if (occurrence.details.direction === "bullish") {
      bucket.bullish += 1;
      bullish += 1;
    } else if (occurrence.details.direction === "bearish") {
      bucket.bearish += 1;
      bearish += 1;
    }
    byPattern.set(code, bucket);

    bySymbol.set(occurrence.symbol, (bySymbol.get(occurrence.symbol) ?? 0) + 1);
    byTimeframe.set(occurrence.timeframe, (byTimeframe.get(occurrence.timeframe) ?? 0) + 1);

    // Las comparaciones van por valor, no por `new Date`: los timestamps llegan
    // como ISO 8601 con zona, donde el orden lexicográfico coincide con el
    // cronológico y no hay que construir objetos Date para comparar.
    if (first === null || occurrence.timestamp < first) first = occurrence.timestamp;
    if (last === null || occurrence.timestamp > last) last = occurrence.timestamp;
  }

  // Se respeta la forma que emite `get_occurrences_summary`: `{symbol, count}` y
  // `{timeframe, count}`, no un mapa `{symbol: count}`. Un consumidor que valga
  // para las dos fuentes no puede depender de claves distintas.
  const toCount = (map: Map<string, number>, key: "symbol" | "timeframe") =>
    Array.from(map.entries())
      .map(([value, count]) => ({ [key]: value, count }))
      .sort((a, b) => Number(b.count) - Number(a.count));

  return {
    total: occurrences.length,
    distinct_patterns: byPattern.size,
    distinct_symbols: bySymbol.size,
    first_occurrence: first,
    last_occurrence: last,
    bullish,
    bearish,
    by_pattern: Array.from(byPattern.entries())
      .map(([pattern_name, v]) => ({
        pattern_name,
        count: v.count,
        // Un codigo tiene una direccion fija, asi que si todas sus filas
        // apuntan al mismo lado ese es el suyo. Con filas mixtas se marca
        // `unknown` en vez de elegir la mayoritaria: avisar de que algo no
        // cuadra vale mas que mentir con un color.
        direction:
          v.bullish > 0 && v.bearish === 0
            ? "bullish"
            : v.bearish > 0 && v.bullish === 0
              ? "bearish"
              : "unknown",
        group: null,
      }))
      .sort((a, b) => Number(b.count) - Number(a.count)),
    by_symbol: toCount(bySymbol, "symbol"),
    by_timeframe: toCount(byTimeframe, "timeframe"),
  };
}

export type PreparedMarker = SeriesMarker<Time> & { seconds: number };

/**
 * Convierte los markers del backend a los de lightweight-charts.
 *
 * Dos cosas no son directo y por eso hay una funcion aparte:
 *
 * 1. **Orden.** `setMarkers` exige el array ordenado por tiempo. El backend lo
 *    entrega descendente, porque `get_occurrences` pagina con
 *    `ORDER BY timestamp DESC` para que la tabla de la UI salga de mas reciente
 *    a mas antigua. Sin reordenar, los markers se dibujan fuera de sitio o la
 *    libreria los descarta.
 * 2. **Correspondencia con velas.** Un marker en una vela que no esta en el
 *    rango no se dibuja y la libreria avisa por consola. Se filtran aqui.
 *
 * El tiempo va como Unix en segundos, que es lo que acepta la libreria cuando
 * `time` es numerico; los indices del servidor se pasan tal cual, sin
 * cuantizar.
 *
 * Los markers cuyo timestamp no coincide con ninguna vela, o cuya serie ya se
 * ha llenado, se descartan aqui en vez de confiar en la libreria.
 */
export function prepareMarkers(
  markers: PatternChartMarker[],
  candleSeconds: Set<number>,
): PreparedMarker[] {
  const seen = new Map<number, PreparedMarker>();
  for (const marker of markers) {
    const seconds = toUnixSeconds(marker.timestamp);
    if (seconds === null || !candleSeconds.has(seconds)) continue;
    // Varias detecciones en la misma vela: la primera gana para no apilar
    // flechas encima. La lista completa sigue estando en OccurrenceTable.
    if (seen.has(seconds)) continue;

    seen.set(seconds, {
      time: seconds as Time,
      position: marker.position,
      shape: marker.shape,
      color: marker.color,
      text: marker.text,
      seconds,
    });
  }
  return Array.from(seen.values()).sort((a, b) => a.seconds - b.seconds);
}
