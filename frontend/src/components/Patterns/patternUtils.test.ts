import { describe, expect, it } from "vitest";
import { prepareMarkers, summarizeOccurrences } from "./patternUtils";
import type { PatternChartMarker, PatternOccurrence } from "../../types/patterns";

/**
 * Tests de la conversion de markers a lightweight-charts.
 *
 * Es la unica logica de `prepareMarkers` que puede fallar sin lanzar excepcion:
 * `setMarkers` acepta un array desordenado y simplemente no pinta nada, asi que
 * un error aqui se manifiesta como "el grafico no muestra detecciones" y es
 * dificil de diagnosticar. El caso del orden descendente es real, porque
 * `get_occurrences` responde con `ORDER BY timestamp DESC`.
 */

function marker(
  timestamp: string,
  overrides: Partial<PatternChartMarker> = {},
): PatternChartMarker {
  return {
    timestamp,
    pattern_name: "MACD_CROSS_BULLISH",
    position: "belowBar",
    shape: "arrowUp",
    color: "#219653",
    text: "MACD +",
    details: { direction: "bullish" },
    ...overrides,
  };
}

const seconds = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);

describe("prepareMarkers", () => {
  it("ordena ascendente aunque el backend los entregue en DESC", () => {
    const candles = new Set([
      seconds("2026-01-01T00:00:00Z"),
      seconds("2026-01-02T00:00:00Z"),
      seconds("2026-01-03T00:00:00Z"),
    ]);
    const markers = [
      marker("2026-01-03T00:00:00Z"),
      marker("2026-01-01T00:00:00Z"),
      marker("2026-01-02T00:00:00Z"),
    ];

    const result = prepareMarkers(markers, candles);

    expect(result.map((m) => m.seconds)).toEqual([
      seconds("2026-01-01T00:00:00Z"),
      seconds("2026-01-02T00:00:00Z"),
      seconds("2026-01-03T00:00:00Z"),
    ]);
  });

  it("convierte el tiempo a segundos Unix conservando el resto de campos", () => {
    const iso = "2026-01-02T03:04:05Z";
    const result = prepareMarkers([marker(iso)], new Set([seconds(iso)]));

    expect(result).toHaveLength(1);
    expect(result[0].time).toBe(seconds(iso));
    expect(result[0].shape).toBe("arrowUp");
    expect(result[0].position).toBe("belowBar");
    expect(result[0].color).toBe("#219653");
    expect(result[0].text).toBe("MACD +");
  });

  it("descarta markers cuya vela no esta en el rango", () => {
    const presente = "2026-01-02T00:00:00Z";
    const candles = new Set([seconds(presente)]);

    const result = prepareMarkers([marker(presente), marker("2025-06-01T00:00:00Z")], candles);

    expect(result).toHaveLength(1);
  });

  it("conserva solo un marker por vela para no apilar flechas", () => {
    const iso = "2026-01-02T00:00:00Z";
    const candles = new Set([seconds(iso)]);

    const result = prepareMarkers(
      [
        marker(iso, { pattern_name: "MACD_CROSS_BULLISH", text: "primero" }),
        marker(iso, { pattern_name: "MA_CROSS_BULLISH", text: "segundo" }),
      ],
      candles,
    );

    expect(result).toHaveLength(1);
    expect(result[0].text).toBe("primero");
  });

  it("descarta timestamps no parseables sin romper el resto", () => {
    const valido = "2026-01-02T00:00:00Z";
    const result = prepareMarkers(
      [marker("no-es-una-fecha"), marker(valido)],
      new Set([seconds(valido)]),
    );

    expect(result).toHaveLength(1);
  });

  it("devuelve lista vacia sin velas", () => {
    expect(prepareMarkers([marker("2026-01-02T00:00:00Z")], new Set())).toEqual([]);
  });
});

/**
 * `summarizeOccurrences` sustituye a `GET /occurrences/summary` en el detalle
 * de un escaneo, así que su forma tiene que coincidir con la del backend: si un
 * campo cambia de sitio, `PatternBreakdown` lee `undefined` y la tarjeta se
 * queda en blanco sin previo aviso.
 */
function occurrence(
  timestamp: string,
  pattern_name: string,
  direction: "bullish" | "bearish" | undefined,
  symbol = "BTCUSDT",
  timeframe = "1h",
): PatternOccurrence {
  return {
    timestamp,
    symbol,
    timeframe,
    pattern_name,
    scan_job_id: "job-1",
    details: direction ? { direction } : {},
  };
}

describe("summarizeOccurrences", () => {
  it("devuelve ceros y listas vacias sin ocurrencias", () => {
    const summary = summarizeOccurrences([]);

    expect(summary.total).toBe(0);
    expect(summary.bullish).toBe(0);
    expect(summary.bearish).toBe(0);
    expect(summary.first_occurrence).toBeNull();
    expect(summary.last_occurrence).toBeNull();
    expect(summary.by_pattern).toEqual([]);
    expect(summary.by_symbol).toEqual([]);
    expect(summary.by_timeframe).toEqual([]);
  });

  it("cuenta y clasifica por direccion", () => {
    const summary = summarizeOccurrences([
      occurrence("2026-01-03T00:00:00Z", "MACD_CROSS_BULLISH", "bullish"),
      occurrence("2026-01-02T00:00:00Z", "MACD_CROSS_BULLISH", "bullish"),
      occurrence("2026-01-01T00:00:00Z", "MACD_CROSS_BEARISH", "bearish"),
      occurrence("2026-01-01T00:00:00Z", "ENGULFING_BULLISH", undefined),
    ]);

    expect(summary.total).toBe(4);
    expect(summary.bullish).toBe(2);
    // La cuarta fila no trae direccion: cuenta en total pero no en ningun lado.
    expect(summary.bearish).toBe(1);
    expect(summary.distinct_patterns).toBe(3);
  });

  it("encuentra primer y ultimo por comparacion lexicografica", () => {
    const summary = summarizeOccurrences([
      occurrence("2026-03-01T10:00:00Z", "MA_CROSS_BULLISH", "bullish"),
      occurrence("2025-12-31T23:59:59Z", "MA_CROSS_BULLISH", "bullish"),
      occurrence("2026-01-15T00:00:00Z", "MA_CROSS_BULLISH", "bullish"),
    ]);

    expect(summary.first_occurrence).toBe("2025-12-31T23:59:59Z");
    expect(summary.last_occurrence).toBe("2026-03-01T10:00:00Z");
  });

  it("ordena los grupos por recuento descendente", () => {
    const summary = summarizeOccurrences([
      occurrence("2026-01-01T00:00:00Z", "RSI_EXIT_OVERSOLD", "bullish"),
      occurrence("2026-01-02T00:00:00Z", "MACD_CROSS_BULLISH", "bullish"),
      occurrence("2026-01-03T00:00:00Z", "MACD_CROSS_BULLISH", "bullish"),
    ]);

    expect(summary.by_pattern.map((r) => r.pattern_name)).toEqual([
      "MACD_CROSS_BULLISH",
      "RSI_EXIT_OVERSOLD",
    ]);
    expect(summary.by_pattern[0].count).toBe(2);
  });

  it("marca unknown cuando un codigo mezcla direcciones", () => {
    const summary = summarizeOccurrences([
      occurrence("2026-01-01T00:00:00Z", "MACD_CROSS_BULLISH", "bullish"),
      occurrence("2026-01-02T00:00:00Z", "MACD_CROSS_BULLISH", "bearish"),
    ]);

    expect(summary.by_pattern[0].direction).toBe("unknown");
  });

  it("usa la misma forma que el backend para by_symbol y by_timeframe", () => {
    const summary = summarizeOccurrences([
      occurrence("2026-01-01T00:00:00Z", "MACD_CROSS_BULLISH", "bullish"),
      occurrence("2026-01-02T00:00:00Z", "MA_CROSS_BULLISH", "bullish", "ETHUSDT", "4h"),
    ]);

    expect(summary.by_symbol).toEqual([
      { symbol: "BTCUSDT", count: 1 },
      { symbol: "ETHUSDT", count: 1 },
    ]);
    expect(summary.by_timeframe).toEqual([
      { timeframe: "1h", count: 1 },
      { timeframe: "4h", count: 1 },
    ]);
  });
});
