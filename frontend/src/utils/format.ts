const pad2 = (n: number): string => n.toString().padStart(2, "0");

function toDate(input: string | Date): Date {
  if (typeof input !== "string") return input;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(input);
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }
  return new Date(input);
}

export function formatDateEs(input: string | Date): string {
  const d = toDate(input);
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
}

export function formatDateTimeEs(input: string | Date): string {
  const d = toDate(input);
  return `${formatDateEs(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/**
 * Backtesting serializa los `Decimal` como string (`"-75.44133916"`) y los
 * `int` como number: estos tres helpers se llevan el `number | string | null`
 * de la API y devuelven un número o `null`, que es lo que los formateadores
 * del módulo pueden pintar. Se mantienen aquí y no en las páginas porque se
 * repiten en la lista, el detalle y las tablas de operaciones.
 */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Dinero en USDT, con separador español y dos decimales. `null` se pinta como
 * «—», que es como el resto del proyecto representa un valor ausente.
 */
export function formatMoney(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return `${n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`;
}

/**
 * Porcentaje cuyo valor ya pone el backend **en tantos por ciento**
 * (`total_return_pct: "-7.544134"` → `-7,54 %`).
 */
export function formatPercent(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return `${n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %`;
}

/**
 * Fraccion en [0, 1] que se quiere pintar en tanto por ciento
 * (`win_rate: "0.421875"` → `42,19 %`). El backend guarda el win_rate como
 * fraccion a proposito (ver `engine._compute_stats`); confundirlo con un
 * porcentaje pintaria un 0,42% donde hay un 42%.
 */
export function formatRate(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return formatPercent(n * 100);
}
