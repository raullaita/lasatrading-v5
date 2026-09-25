import type { ImportJobCombination } from "../../types/dataImport";
import { StatusBadge } from "./StatusBadge";

export function CombinationList({ combinations }: { combinations: ImportJobCombination[] }) {
  if (combinations.length === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Sin combinaciones registradas.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            <th className="px-4 py-2">Símbolo</th>
            <th className="px-4 py-2">Timeframe</th>
            <th className="px-4 py-2">Estado</th>
            <th className="px-4 py-2 text-right">Insert</th>
            <th className="px-4 py-2 text-right">Update</th>
            <th className="px-4 py-2 text-right">Skip</th>
            <th className="px-4 py-2">Última vela</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {combinations.map((c) => (
            <tr key={c.id}>
              <td className="px-4 py-2 font-medium text-slate-800 dark:text-slate-200">{c.symbol}</td>
              <td className="px-4 py-2 text-slate-600 dark:text-slate-300">{c.timeframe}</td>
              <td className="px-4 py-2">
                <StatusBadge status={c.status} />
              </td>
              <td className="px-4 py-2 text-right text-slate-600 dark:text-slate-300">
                {c.candles_inserted.toLocaleString("es")}
              </td>
              <td className="px-4 py-2 text-right text-slate-600 dark:text-slate-300">
                {c.candles_updated.toLocaleString("es")}
              </td>
              <td className="px-4 py-2 text-right text-slate-600 dark:text-slate-300">
                {c.candles_skipped.toLocaleString("es")}
              </td>
              <td className="px-4 py-2 text-slate-500 dark:text-slate-400">
                {c.last_candle_at
                  ? new Date(c.last_candle_at).toLocaleString("es")
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}