import type { WalkForwardVerdict } from "../../types/walkForward";

/**
 * La cuenta del coste, y la estimacion de ventanas.
 *
 * Vive fuera del componente del formulario por dos razones. La primera es que es
 * lo unico de esa pantalla que se puede comprobar con un test sin DOM: el numero
 * de simulaciones es la cifra que decide si el boton se habilita, y una
 * cuenta equivocada ahi no da una excepcion, da un boton pulsable que lanza
 * 1.800 simulaciones cuando el usuario creia que iban a ser doce.
 *
 * La segunda es que la regla de "que celdas son simulables" esta **duplicada**
 * en el backend, en tres sitios: el conteo de simulaciones del motor, el
 * ``base_strategy`` que elige la primera celda, y el validador del schema que
 * devuelve el 422. Esta es la cuarta copia, y no puede conocer la del backend,
 * pero si puede seguir la misma regla y documentar de donde viene.
 */

/**
 * Celdas de la rejilla que el motor puede simular de verdad.
 *
 * Una celda con take profit y stop loss a la vez no se puede simular: sin
 * niveles no hay forma de cerrar la posicion antes de ``max_hold``, y el motor
 * la salta en vez de abortar las otras. Contarla aqui inflaria el coste que se
 * le enseña al usuario, y el usuario lo pagaria.
 */
export function combinacionesSimulables(
  takeProfit: readonly (number | null)[],
  stopLoss: readonly (number | null)[],
  maxHolds: readonly number[],
): number {
  let pares = 0;
  for (const tp of takeProfit) {
    for (const sl of stopLoss) {
      if (tp !== null || sl !== null) pares += 1;
    }
  }
  return pares * maxHolds.length;
}

/**
 * Ventanas que saldrán, **estimadas**.
 *
 * Usa el mismo reparto que `walk_forward.build_windows`: se avanza el cursor
 * `step_days` y se cuenta mientras quepa una ventana in-sample entera mas su
 * out-of-sample, descontando la reserva final.
 *
 * El adjective "estimadas" es lo importante. El motor cuenta sobre el primer y el
 * ultimo timestamp **real** de las velas, y el navegador no tiene ese dato: solo
 * tiene el rango declarado del escaneo. Si el rango declarado y el real no
 * coinciden al dia, el numero puede diferir en una ventana. Poner un numero
 * exacto en pantalla seria mentir por un detalle que el usuario no puede
 * comprobar, y el numero exacto llega igualmente en el 422 del backend.
 */
export function ventanasEstimadas(
  dias: number,
  windowDays: number,
  oosDays: number,
  stepDays: number,
  holdoutDays: number,
): number {
  const utiles = dias - holdoutDays;
  if (windowDays <= 0 || oosDays <= 0 || stepDays <= 0) return 0;
  let count = 0;
  let cursor = 0;
  while (cursor + windowDays + oosDays <= utiles) {
    count += 1;
    cursor += stepDays;
  }
  return count;
}

export interface CosteEstimado {
  combinaciones: number;
  ventanas: number;
  simulaciones: number;
  dias: number;
}

/** El numero grande de la pantalla, en una sola llamada. */
export function estimarCoste(params: {
  takeProfit: readonly (number | null)[];
  stopLoss: readonly (number | null)[];
  maxHolds: readonly number[];
  dias: number;
  windowDays: number;
  oosDays: number;
  stepDays: number;
  holdoutDays: number;
}): CosteEstimado {
  const combinaciones = combinacionesSimulables(
    params.takeProfit,
    params.stopLoss,
    params.maxHolds,
  );
  const ventanas = ventanasEstimadas(
    params.dias,
    params.windowDays,
    params.oosDays,
    params.stepDays,
    params.holdoutDays,
  );
  return {
    combinaciones,
    ventanas,
    simulaciones: combinaciones * ventanas,
    dias: params.dias,
  };
}

/**
 * Dias que cubre un escaneo, a partir de su rango declarado.
 *
 * Se cuenta en UTC a proposito: con las fechas locales, un rango que empieza y
 * acaba en el mismo dia da 0 dias, y el formulario dice que no sale ninguna
 * ventana de un escaneo que tiene doce meses de velas.
 */
export function diasDeRango(dateFrom: string, dateTo: string): number {
  const desde = new Date(dateFrom).getTime();
  const hasta = new Date(dateTo).getTime();
  if (Number.isNaN(desde) || Number.isNaN(hasta) || hasta < desde) return 0;
  return Math.round((hasta - desde) / 86_400_000);
}

/** Como se muestra una combinacion: `null` es "sin este nivel", no un cero. */
export function etiquetaEstrategia(estrategia: {
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_hold: number;
}): string {
  const tp = estrategia.take_profit_pct === null ? "sin TP" : `TP ${estrategia.take_profit_pct}%`;
  const sl = estrategia.stop_loss_pct === null ? "sin SL" : `SL ${estrategia.stop_loss_pct}%`;
  return `${tp} / ${sl} / ${estrategia.max_hold}v`;
}

/** Igual, para una candidata, donde los niveles llegan como texto decimal. */
export function etiquetaCandidata(candidata: {
  take_profit_pct: string | number | null;
  stop_loss_pct: string | number | null;
  max_hold: number;
}): string {
  return etiquetaEstrategia({
    take_profit_pct: candidata.take_profit_pct === null ? null : Number(candidata.take_profit_pct),
    stop_loss_pct: candidata.stop_loss_pct === null ? null : Number(candidata.stop_loss_pct),
    max_hold: candidata.max_hold,
  });
}

/**
 * El IC95% con su propio formato, y la razon de que tenga uno.
 *
 * Un intervalo metido en una celda de porcentaje con signo se lee mal:
 * `[-41,20, 318,75]` parecen dos cifras sueltas y no un intervalo de unus. Se
 * escribe `[desde; hasta]%` y el signo va solo en el extremo que lo necesita.
 *
 * Y `null` sale como guion, no como `0,00%`. Una candidata descartada por no
 * llegar al minimo de operaciones **no tiene** intervalo, y enseñar un 0,00%
 * seria afirmar que su retorno es cero con certeza, que es justo lo contrario
 * de lo que significa un intervalo que incluye el cero.
 */
export function formatearIC(
  low: string | number | null,
  high: string | number | null,
): { texto: string; cruzaCero: boolean | null } {
  if (low === null || high === null) return { texto: "—", cruzaCero: null };
  const desde = Number(low);
  const hasta = Number(high);
  if (Number.isNaN(desde) || Number.isNaN(hasta)) {
    return { texto: "—", cruzaCero: null };
  }
  return {
    texto: `[${desde < 0 ? "" : " "}${desde.toFixed(1)}; ${hasta.toFixed(1)}]%`,
    cruzaCero: desde <= 0 && hasta >= 0,
  };
}

/**
 * El texto que explica el veredicto.
 *
 * Va **completo** y no como etiqueta suelta. «Prometedora» no dice por que es
 * prometedora, y un usuario que ve solo el color tiene tres formas distintas de
 * interpretar la misma palabra: una la will read como "va bien", otra como
 * "casi", y otra ni se lo pregunta. El texto cierra las tres.
 */
export const TEXTO_VERDICT: Record<WalkForwardVerdict, string> = {
  sostenida:
    "Pasa todas las guardas, el intervalo de confianza excluye el cero y se ha evaluado en tres regímenes o más. Es el único veredicto que dice algo sobre más de un mercado.",
  prometedora:
    "Pasa todas las guardas, pero el intervalo de confianza incluye el cero: el resultado es compatible con haber sido azar. Merece una segunda mirada, no una decisión.",
  descartada:
    "No pasa las guardas duras. El motivo está en cada fila: sin operaciones, sin ventanas suficientes, o sin superar al mercado.",
};
