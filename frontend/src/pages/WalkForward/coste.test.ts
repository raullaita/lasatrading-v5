import { describe, expect, it } from "vitest";

import {
  simulableCombinations,
  daysFromRange,
  estimateCost,
  etiquetaCandidata,
  etiquetaEstrategia,
  formatearIC,
  TEXTO_VERDICT,
  estimatedWindows,
} from "./coste";

/**
 * Tests de la cuenta del coste y del formato del veredicto.
 *
 * Aqui no hay DOM que probar: la pantalla de configuracion es JSX, y lo unico
 * que puede estar mal en ella es la **cuenta**. Un contador que dice 12
 * simulaciones cuando son 1.800 no lanza ninguna excepcion: deja al usuario
 * launch un trabajo de dos minutos creyendo que eran doce, y eso solo se
 * comprueba aqui.
 *
 * El numero de celdas simulables esta duplicado en el backend por tres veces
 * (`_combinaciones_validas`, `base_strategy` y el validador del schema). Esta es
 * la cuarta copia, y no puede conocer las de alla, asi que lo que se comprueba
 * es que siga **la misma regla** que el motor, que es la que esta escrita en el
 * docstring de `_celdas_validas`.
 */
describe("celdas simulables", () => {
  it("cuenta el producto de los tres ejes", () => {
    expect(simulableCombinations([null, 2.0], [1.0, 1.5], [12, 24])).toBe(8);
  });

  it("excluye la celda sin take profit y sin stop loss", () => {
    // Sin niveles no hay forma de cerrar antes de `max_hold`, y el motor la salta.
    // Contarla inflaria el coste que se le ensena al usuario, y el usuario lo
    // pagaria: seria un boton que dice 2.400 simulaciones y son 1.200.
    expect(simulableCombinations([null], [null], [12, 24])).toBe(0);
  });

  it("cuenta las celdas con un solo nivel, que si son validas", () => {
    // `sin TP` con SL es una estrategia legitima: cierra por stop o por tiempo.
    expect(simulableCombinations([null], [1.0], [12])).toBe(1);
    expect(simulableCombinations([2.0], [null], [12])).toBe(1);
  });

  it("no se confunde con contar el producto a pelo", () => {
    // El producto bruto daria 4; el correcto es 3, porque la celda (null, null)
    // no se puede simular.
    expect(simulableCombinations([null, 2.0], [null, 1.0], [12])).toBe(3);
  });
});

describe("ventanas estimadas", () => {
  it("reparte el rango con el mismo criterio que el motor", () => {
    // 365 dias, ventanas de 90+30 y paso 30: caben 11 enteras (120 dias cada
    // una), y la ultima ventana que no cabe entera no se recorta, se descarta.
    expect(estimatedWindows(365, 90, 30, 30, 0)).toBe(9);
  });

  it("devuelve cero cuando no cabe ni una ventana entera", () => {
    // Y no "una ventana recortada": una ventana incompleta al final no se
    // recorta, se descarta, porque su OOS no tendria los dias que la ISAssume.
    expect(estimatedWindows(100, 90, 30, 30, 0)).toBe(0);
  });

  it("descuenta la reserva final antes de repartir", () => {
    const sinReserva = estimatedWindows(365, 90, 30, 90, 0);
    const conReserva = estimatedWindows(365, 90, 30, 90, 120);
    expect(conReserva).toBeLessThan(sinReserva);
  });

  it("no divide por cero con parametros absurdos", () => {
    // Los campos numericos del formulario llegan vacios mientras se teclea, y
    // `Number("")` es 0. Un paso de cero aqui es un bucle infinito colgado en
    // el navegador, no un error visible.
    expect(estimatedWindows(365, 90, 30, 0, 0)).toBe(0);
    expect(estimatedWindows(365, 0, 30, 30, 0)).toBe(0);
    expect(estimatedWindows(365, 90, 0, 30, 0)).toBe(0);
  });
});

describe("daysFromRange", () => {
  it("cuenta los dias de un rango declarado", () => {
    expect(daysFromRange("2021-09-01T00:00:00Z", "2021-12-31T00:00:00Z")).toBe(121);
  });

  it("da cero en un rango invertido o ilegible, no un numero negativo", () => {
    expect(daysFromRange("2021-12-31T00:00:00Z", "2021-09-01T00:00:00Z")).toBe(0);
    expect(daysFromRange("no-es-fecha", "tampoco")).toBe(0);
  });
});

describe("estimateCost", () => {
  it("multiplica combinaciones por ventanas", () => {
    const coste = estimateCost({
      takeProfit: [null, 2.0],
      stopLoss: [1.0, 1.5],
      maxHolds: [12, 24],
      days: 730,
      windowDays: 90,
      oosDays: 30,
      stepDays: 120,
      holdoutDays: 0,
    });
    expect(coste.combinations).toBe(8);
    expect(coste.windows).toBeGreaterThan(0);
    expect(coste.simulations).toBe(coste.combinations * coste.windows);
  });

  it("da cero cuando el rango no da ninguna ventana, y no un numero pequeno", () => {
    const coste = estimateCost({
      takeProfit: [2.0],
      stopLoss: [1.0],
      maxHolds: [12],
      days: 40,
      windowDays: 90,
      oosDays: 30,
      stepDays: 30,
      holdoutDays: 0,
    });
    expect(coste.windows).toBe(0);
    expect(coste.simulations).toBe(0);
  });
});

describe("etiqueta de una combinacion", () => {
  it("distingue 'sin TP' de un take profit del 0%", () => {
    // La distincion es del motor entero: `None` es "no hay este nivel" y `0.0`
    // seria un take profit del cero, que es otra estrategia distinta e
    // invalida. Si la etiqueta colapsa los dos, el usuario no puede distinguir
    // en la tabla dos filas que el motor si distingue.
    expect(etiquetaEstrategia({ take_profit_pct: null, stop_loss_pct: 1.5, max_hold: 24 })).toBe(
      "sin TP / SL 1.5% / 24v",
    );
    expect(etiquetaEstrategia({ take_profit_pct: 0, stop_loss_pct: 1.5, max_hold: 24 })).toBe(
      "TP 0% / SL 1.5% / 24v",
    );
  });

  it("convierte los decimales que llegan como texto", () => {
    expect(
      etiquetaCandidata({ take_profit_pct: "2.00", stop_loss_pct: "1.00", max_hold: 12 }),
    ).toBe("TP 2% / SL 1% / 12v");
  });
});

describe("el IC95% tiene formato propio", () => {
  it("lo escribe como intervalo, no como dos cifras sueltas", () => {
    // `[-41,20, 318,75]` en una celda de porcentaje con signo se lee como dos
    // numeros que no tienen relacion. El intervalo lleva su propia sintaxis.
    const { texto } = formatearIC("-41.2", "318.75");
    expect(texto).toBe("[-41.2; 318.8]%");
  });

  it("marca cuando el intervalo incluye el cero", () => {
    // Es la diferencia entre "prometedora" y "sostenida", y por eso el color de
    // la celda depende de esto y no de si el numero es bonito.
    expect(formatearIC("-41.2", "318.75").cruzaCero).toBe(true);
    expect(formatearIC("2.0", "31.0").cruzaCero).toBe(false);
    expect(formatearIC("-31.0", "-2.0").cruzaCero).toBe(false);
  });

  it("pone guion cuando no hay intervalo, y no un cero", () => {
    // Una candidata descartada por no llegar al minimo de operaciones no tiene
    // intervalo. Enseñar `0,00%` seria afirmar que su retorno es cero con
    // certeza, que es justo lo contrario de lo que significa un intervalo que
    // incluye el cero.
    const { texto, cruzaCero } = formatearIC(null, null);
    expect(texto).toBe("—");
    expect(cruzaCero).toBeNull();
  });

  it("acepta numeros y texto, que es como llegan segun el sitio", () => {
    expect(formatearIC(-41.2, 318.75).texto).toBe("[-41.2; 318.8]%");
  });
});

describe("el texto del veredicto", () => {
  it("explica los tres grados y no los deja solo como una etiqueta", () => {
    for (const veredicto of ["sostenida", "prometedora", "descartada"] as const) {
      expect(TEXTO_VERDICT[veredicto].length).toBeGreaterThan(40);
    }
  });

  it("dice expresamente lo que hace que no sea 'sostenida'", () => {
    // La razon por la que el motor no sube de grado es el IC, asi que el texto
    // de 'prometedora' tiene que decir именно eso. Si no lo dice, el usuario
    // cree que le faltaron datos cuando lo que le falto fue que el intervalo no
    // excluyera el cero.
    expect(TEXTO_VERDICT.prometedora).toContain("cero");
    expect(TEXTO_VERDICT.sostenida).toContain("cero");
    expect(TEXTO_VERDICT.sostenida).toContain("tres");
  });
});
