import type { ImportJobCombination } from "../../types/dataImport";
import { StatusBadge } from "./StatusBadge";

export function CombinationList({ combinations }: { combinations: ImportJobCombination[] }) {
  if (combinations.length === 0) {
    return <p className="text-sm text-slate-500">Sin combinaciones registradas.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
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
        <tbody className="divide-y divide-slate-100">
          {combinations.map((c) => (
            <tr key={c.id}>
              <td className="px-4 py-2 font-medium text-slate-800">{c.symbol}</td>
              <td className="px-4 py-2 text-slate-600">{c.timeframe}</td>
              <td className="px-4 py-2">
                <StatusBadge status={c.status} />
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                {c.candles_inserted.toLocaleString("es")}
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                {c.candles_updated.toLocaleString("es")}
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                {c.candles_skipped.toLocaleString("es")}
              </td>
              <td className="px-4 py-2 text-slate-500">
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