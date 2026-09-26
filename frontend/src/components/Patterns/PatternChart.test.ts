import { describe, expect, it } from "vitest";
import { prepareMarkers } from "./PatternChart";
import type { PatternChartMarker } from "../../types/patterns";

/**
 * Tests de la conversion de markers a lightweight-charts.
 *
 * Es la unica logica de `PatternChart` que puede fallar sin lanzar excepcion:
 * `setMarkers` acepta un array desordenado y simplemente no pinta nada, asi que
 * un error aqui se manifiesta como "el grafico no muestra detecciones" y es
 * dificil de diagnosticar. El caso del orden descendente es real, porque
 * `get_occurrences` responde con `ORDER BY timestamp DESC`.
 */

function marker(
  timestamp: string,
  overrides: Partial<PatternChartMarker> = {}
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

    const result = prepareMarkers(
      [marker(presente), marker("2025-06-01T00:00:00Z")],
      candles
    );

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
      candles
    );

    expect(result).toHaveLength(1);
    expect(result[0].text).toBe("primero");
  });

  it("descarta timestamps no parseables sin romper el resto", () => {
    const valido = "2026-01-02T00:00:00Z";
    const result = prepareMarkers(
      [marker("no-es-una-fecha"), marker(valido)],
      new Set([seconds(valido)])
    );

    expect(result).toHaveLength(1);
  });

  it("devuelve lista vacia sin velas", () => {
    expect(prepareMarkers([marker("2026-01-02T00:00:00Z")], new Set())).toEqual(
      []
    );
  });
});
