import { useMemo, useState } from "react";
import { Crosshair } from "lucide-react";
import type { PatternDirection, PatternOccurrence } from "../../types/patterns";

/**
 * Filas que se pintan de golpe. El endpoint de ocurrencias admite `page_size`
 * alto y el chart llega a pedir hasta 5.000, así que hay un "mostrar más" en
 * vez de renderizar el listado entero: 5.000 filas con un `<details>` cada una
 * son 15.000 nodos y el navegador empieza a_ir_al_dash.
 */
const PAGE_SIZE = 50;

/**
 * La dirección sale de `details.direction`, nunca del nombre del patrón.
 *
 * Es tentador deducirla de `RSI_EXIT_OVERSOLD → bullish` leyendo el código,
 * y funciona hasta que aparece `RSI_EXIT_OVERBOUGHT`, que es bearish. El
 * scanner ya la escribe en los detalles, así que se lee de ahí y el catálogo
 * deja de ser una fuente de verdad duplicada.
 */
function readDirection(occurrence: PatternOccurrence): PatternDirection | "unknown" {
  const value = occurrence.details.direction;
  return value === "bullish" || value === "bearish" ? value : "unknown";
}

const BADGE_STYLES: Record<PatternDirection | "unknown", string> = {
  bullish: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  bearish: "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  unknown: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

const DIRECTION_LABELS: Record<PatternDirection | "unknown", string> = {
  bullish: "alcista",
  bearish: "bajista",
  unknown: "sin dirección",
};

const UNKNOWN_DIRECTION = "text-slate-400 italic dark:text-slate-500";

function formatTimestamp(iso: string): { main: string; relative: string } | null {
  // El backend emite ISO 8601 con microsegundos y zona. `Date` los recorta a
  // milisegundos sin problema, pero un parseo fallido se detecta aqui para no
  // pintar "Invalid Date" en la columna.
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return {
    main: date.toLocaleString("es-ES", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    relative: date.toLocaleString("es-ES", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
  };
}

/** Números con decimales útiles: 2.0 no necesita cuatro cifras. */
function formatValue(value: number | string | undefined): string {
  if (value === undefined) return "—";
  if (typeof value === "string") return value;
  if (Number.isInteger(value)) return String(value);
  return value.toLocaleString("es-ES", { maximumFractionDigits: 4 });
}

function MetadataCell({ occurrence }: { occurrence: PatternOccurrence }) {
  const entries = Object.entries(occurrence.details).filter(([key]) => key !== "direction");

  if (entries.length === 0) {
    return <span className={UNKNOWN_DIRECTION}>sin metadatos</span>;
  }

  return (
    <details className="group">
      <summary className="cursor-pointer list-none text-xs text-indigo-600 hover:underline dark:text-indigo-400">
        Ver {entries.length} {entries.length === 1 ? "campo" : "campos"}
      </summary>
      <dl className="mt-1.5 space-y-0.5 rounded-md bg-slate-50 p-2 dark:bg-slate-800/60">
        {entries.map(([key, value]) => (
          <div key={key} className="flex gap-2 text-[11px]">
            <dt className="shrink-0 font-medium text-slate-500 dark:text-slate-400">{key}:</dt>
            <dd className="truncate font-mono text-slate-700 dark:text-slate-200">
              {formatValue(value)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function OccurrenceTable({
  occurrences,
  onViewChart,
  emptyMessage = "Sin ocurrencias para los filtros seleccionados.",
}: {
  occurrences: PatternOccurrence[];
  /** Lleva la vista del gráfico a esa vela. Lo llama "Ver en gráfico". */
  onViewChart: (timestamp: string) => void;
  emptyMessage?: string;
}) {
  const [visible, setVisible] = useState(PAGE_SIZE);

  const rows = useMemo(() => occurrences.slice(0, visible), [occurrences, visible]);

  if (occurrences.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        {emptyMessage}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 dark:bg-slate-800/60">
            <tr className="text-slate-500 dark:text-slate-400">
              <th className="px-3 py-2 font-semibold">Fecha/Hora</th>
              <th className="px-3 py-2 font-semibold">Símbolo</th>
              <th className="px-3 py-2 font-semibold">Patrón</th>
              <th className="px-3 py-2 font-semibold">Metadata</th>
              <th className="px-3 py-2 text-right font-semibold">Acción</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((occurrence) => {
              const direction = readDirection(occurrence);
              const stamp = formatTimestamp(occurrence.timestamp);
              // `PatternOccurrence` no trae id propio: la combinación de
              // timestamp, patrón y job es única dentro de una respuesta.
              const key = `${occurrence.scan_job_id}:${occurrence.pattern_name}:${occurrence.timestamp}`;

              return (
                <tr
                  key={key}
                  className="align-top transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
                >
                  <td className="whitespace-nowrap px-3 py-2">
                    {stamp ? (
                      <>
                        <span className="block font-medium text-slate-700 dark:text-slate-200">
                          {stamp.main}
                        </span>
                        <span className="block text-[10px] text-slate-400 dark:text-slate-500">
                          {stamp.relative}
                        </span>
                      </>
                    ) : (
                      <span className="text-rose-600 dark:text-rose-400">
                        {occurrence.timestamp}
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span className="block font-medium text-slate-700 dark:text-slate-200">
                      {occurrence.symbol}
                    </span>
                    <span className="block text-[10px] text-slate-400 dark:text-slate-500">
                      {occurrence.timeframe}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${BADGE_STYLES[direction]}`}
                      title={`Dirección: ${DIRECTION_LABELS[direction]}`}
                    >
                      {DIRECTION_LABELS[direction]}
                    </span>
                    <span className="mt-1 block font-mono text-[11px] text-slate-600 dark:text-slate-300">
                      {occurrence.pattern_name}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <MetadataCell occurrence={occurrence} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => onViewChart(occurrence.timestamp)}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-[11px] font-medium text-slate-700 transition-colors hover:border-indigo-400 hover:text-indigo-600 dark:border-slate-700 dark:text-slate-300 dark:hover:border-indigo-400 dark:hover:text-indigo-400"
                    >
                      <Crosshair className="h-3 w-3" />
                      Ver en gráfico
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {visible < occurrences.length && (
        <button
          type="button"
          onClick={() => setVisible((prev) => prev + PAGE_SIZE)}
          className="w-full rounded-lg border border-dashed border-slate-300 py-2 text-xs font-medium text-slate-500 hover:border-indigo-400 hover:text-indigo-600 dark:border-slate-700 dark:text-slate-400 dark:hover:border-indigo-400 dark:hover:text-indigo-400"
        >
          Mostrar más ({occurrences.length - visible} restantes)
        </button>
      )}
    </div>
  );
}
