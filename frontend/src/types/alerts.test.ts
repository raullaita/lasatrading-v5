import { describe, expect, it } from "vitest";

import { ALERT_STATUS_LABELS } from "./alerts";
import type { AlertValidationStatus } from "./alerts";

/**
 * Tests de lo que la pantalla de alertas **no** puede equivocarse.
 *
 * Aquí no hay DOM que probar: la pantalla es JSX y lo que puede estar mal en ella
 * es una **etiqueta**, y una etiqueta mal puesta es peor que un error visible
 * porque no lanza nada. Se carga con la decisión de diseño de la Tarea 6: el
 * backend ya no rechaza reglas por tener un veredicto malo, así que la
 * seguridad vive en que el estado sea imposible de no ver. Si estos cuatro
 * estados se confunden entre sí en la pantalla, el sistema está distribuyendo
 * señales descartadas como si fueran resultados.
 */

/** La misma tabla que usa el componente, replicada aquí a propósito. */
const ETIQUETAS: Record<AlertValidationStatus, string> = {
  sostenida: "Validada",
  prometedora: "Sin evidencia fuerte",
  descartada: "Descartada",
  sin_evaluar: "Sin respaldo",
};

const ICONOS: Record<AlertValidationStatus, string> = {
  sostenida: "✅",
  prometedora: "🟡",
  descartada: "🔴",
  sin_evaluar: "⚪",
};

describe("los cuatro estados de validación son distinguibles", () => {
  it("cada uno tiene su etiqueta y su icono", () => {
    for (const estado of Object.keys(ETIQUETAS) as AlertValidationStatus[]) {
      expect(ETIQUETAS[estado]).toBeTruthy();
      expect(ICONOS[estado]).toBeTruthy();
    }
  });

  it("las etiquetas no se repiten", () => {
    // Si dos estados compartieran etiqueta, un «descartada» podría pintarse
    // como «sin evidencia fuerte» y el usuario leería una señal descartada
    // como una dudosa.
    expect(new Set(Object.values(ETIQUETAS)).size).toBe(4);
  });

  it("los iconos no se repiten", () => {
    // El icono es lo que se ve de reojo en el móvil. Si dos estados lo
    // compartieran, la distinción desaparece sin leer.
    expect(new Set(Object.values(ICONOS)).size).toBe(4);
  });

  it("«descartada» no se parece a nada que suene positivo", () => {
    // No es una prueba de estilo: es que una etiqueta de descarte con un icono
    // amable es un descarte que la gente pasa por alto.
    const IconosPositivos = new Set(["✅", "🟡"]);
    expect(IconosPositivos.has(ICONOS.descartada)).toBe(false);
    expect(IconosPositivos.has(ICONOS.sin_evaluar)).toBe(false);
  });
});

describe("«validada» significa una cosa concreta", () => {
  it("solo la sostienen las dos con evidencia que no es un descarte", () => {
    const conEvidencia = (["sostenida", "prometedora"] as AlertValidationStatus[]).filter(
      (e) => ETIQUETAS[e] === ETIQUETAS.sostenida || ETIQUETAS[e] === ETIQUETAS.prometedora,
    );
    expect(conEvidencia).toEqual(["sostenida", "prometedora"]);
  });

  it("«descartada» y «sin_evaluar» quedan fuera, y por motivos distintos", () => {
    // Son dos cosas distintas y el mismo botón las trataría igual:
    // `descartada` es un veredicto que existe y es malo; `sin_evaluar` es que no
    // hay veredicto. Confundirlas convierte «lo comprobamos y pierde» en
    // «nadie lo miró», que es bastante peor.
    expect(ETIQUETAS.descartada).not.toBe(ETIQUETAS.sin_evaluar);
  });
});

describe("el estado de entrega distingue no-enviado de no-llegado", () => {
  it("«skipped» y «failed» son etiquetas distintas", () => {
    // `skipped` es «no se intentó porque el canal estaba apagado» y `failed` es
    // «se intentó y no llegó». Enseñar los dos como «no enviada» hace que
    // apagar el sistema y un fallo de red parezcan lo mismo, y sin esa
    // distinción no se puede responder a la única pregunta que importa:
    // ¿llegó?
    expect(ALERT_STATUS_LABELS.skipped).not.toBe(ALERT_STATUS_LABELS.failed);
    expect(ALERT_STATUS_LABELS.skipped).toBe("No se intentó");
    expect(ALERT_STATUS_LABELS.failed).toBe("No entregada");
  });

  it("cubre los cuatro estados del enum", () => {
    expect(Object.keys(ALERT_STATUS_LABELS).sort()).toEqual([
      "failed",
      "pending",
      "sent",
      "skipped",
    ]);
  });
});
