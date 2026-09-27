import { useMemo } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { OccurrenceGroupCount, OccurrenceSummary } from "../../types/patterns";

/**
 * Resumen agregado de las ocurrencias: total, reparto alcista/bajista y
 * desglose por patron.
 *
 * Todos los numeros vienen ya calculados por `GET /occurrences/summary`. En
 * concreto `bullish` y `bearish` los calcula el backend cruzando cada codigo
 * contra el catalogo, no leyendo `details.direction` de las filas: asi el
 * reparto sale bien incluso si alguna fila antigua viniera sin direccion. Este
 * componente no recalcula nada de eso.
 */

const PATTERN_LABELS: Record<string, string> = {
  MACD_CROSS_BULLISH: "Cruce MACD alcista",
  MACD_CROSS_BEARISH: "Cruce MACD bajista",
  RSI_EXIT_OVERSOLD: "Salida de sobreventa",
  RSI_EXIT_OVERBOUGHT: "Salida de sobrecompra",
  BB_BREAKOUT_UPPER: "Ruptura banda superior",
  BB_BREAKOUT_LOWER: "Ruptura banda inferior",
  MA_CROSS_BULLISH: "Cruce de medias alcista",
  MA_CROSS_BEARISH: "Cruce de medias bajista",
  ENGULFING_BULLISH: "Vela envolvente alcista",
  ENGULFING_BEARISH: "Vela envolvente bajista",
};

function labelFor(code: string): string {
  return PATTERN_LABELS[code] ?? code;
}

/** `by_pattern` viene como lista de objetos libres; se estrecha aqui. */
function patternRows(
  rows: OccurrenceGroupCount[],
): { code: string; count: number; direction: string }[] {
  return rows
    .map((row) => ({
      code: typeof row.pattern_name === "string" ? row.pattern_name : "",
      count: typeof row.count === "number" ? row.count : 0,
      direction: typeof row.direction === "string" ? row.direction : "unknown",
    }))
    .filter((row) => row.code !== "");
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function PatternBreakdown({ summary }: { summary: OccurrenceSummary }) {
  const rows = useMemo(
    () => patternRows(summary.by_pattern).sort((a, b) => b.count - a.count),
    [summary.by_pattern],
  );

  const total = summary.total;
  const bullish = summary.bullish;
  const bearish = summary.bearish;
  const classified = bullish + bearish;

  // `classified` puede ser menor que `total` si algun patron no esta en el
  // catalogo: el backend cuenta esos como "unknown" y no los mete en ninguno de
  // los dos lados. Los porcentajes se calculan sobre lo clasificado, no sobre
  // el total, para que la barra no mienta.
  const bullishPct = classified > 0 ? (bullish / classified) * 100 : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Total de ocurrencias
          </p>
          <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-slate-100">
            {total.toLocaleString("es-ES")}
          </p>
          <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
            {summary.distinct_patterns} {summary.distinct_patterns === 1 ? "patrón" : "patrones"} ·{" "}
            {summary.distinct_symbols} {summary.distinct_symbols === 1 ? "símbolo" : "símbolos"}
          </p>
          <p className="text-[11px] text-slate-400 dark:text-slate-500">
            {formatDate(summary.first_occurrence)} → {formatDate(summary.last_occurrence)}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 sm:col-span-2 dark:border-slate-800 dark:bg-slate-900">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Alcistas vs Bajistas
          </p>
          <div className="mt-2 flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <ArrowUpRight className="h-4 w-4 text-emerald-500" />
              <span className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                {bullish.toLocaleString("es-ES")}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {classified > 0 ? `${bullishPct.toFixed(1)}%` : "—"}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <ArrowDownRight className="h-4 w-4 text-rose-500" />
              <span className="text-2xl font-bold text-rose-600 dark:text-rose-400">
                {bearish.toLocaleString("es-ES")}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {classified > 0 ? `${(100 - bullishPct).toFixed(1)}%` : "—"}
              </span>
            </div>
          </div>

          <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className="bg-emerald-500 transition-all"
              style={{ width: `${classified > 0 ? bullishPct : 0}%` }}
            />
            <div
              className="bg-rose-500 transition-all"
              style={{ width: `${classified > 0 ? 100 - bullishPct : 0}%` }}
            />
          </div>
          {classified < total && (
            <p className="mt-2 text-[11px] text-amber-600 dark:text-amber-400">
              {total - classified}{" "}
              {total - classified === 1
                ? "ocurrencia sin dirección clasificada"
                : "ocurrencias sin dirección clasificada"}
              : su patrón no está en el catálogo.
            </p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h4 className="mb-3 text-sm font-bold text-slate-900 dark:text-slate-100">
          Desglose por patrón
        </h4>
        {rows.length === 0 ? (
          <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
            Ningún patrón para desglosar
          </p>
        ) : (
          <ul className="space-y-2">
            {rows.map((row) => {
              const pct = total > 0 ? (row.count / total) * 100 : 0;
              return (
                <li key={row.code}>
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          row.direction === "bullish"
                            ? "bg-emerald-500"
                            : row.direction === "bearish"
                              ? "bg-rose-500"
                              : "bg-slate-400"
                        }`}
                      />
                      <span className="truncate text-slate-700 dark:text-slate-200">
                        {labelFor(row.code)}
                      </span>
                      <span className="shrink-0 font-mono text-[10px] text-slate-400 dark:text-slate-500">
                        {row.code}
                      </span>
                    </span>
                    <span className="shrink-0 font-medium text-slate-600 dark:text-slate-300">
                      {row.count.toLocaleString("es-ES")}
                      <span className="ml-1 text-[10px] font-normal text-slate-400 dark:text-slate-500">
                        ({pct.toFixed(1)}%)
                      </span>
                    </span>
                  </div>
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div
                      className={`h-full transition-all ${
                        row.direction === "bearish" ? "bg-rose-400" : "bg-emerald-400"
                      }`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
