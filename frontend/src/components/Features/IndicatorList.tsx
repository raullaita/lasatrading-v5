import type { IndicatorConfig } from "../../types/features";

export function IndicatorList({ indicators }: { indicators: IndicatorConfig[] }) {
  if (indicators.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">Sin indicadores configurados.</p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            <th className="px-4 py-2">Indicador</th>
            <th className="px-4 py-2">Parámetros</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {indicators.map((ind) => (
            <tr key={`${ind.name}-${JSON.stringify(ind.params)}`}>
              <td className="px-4 py-2 font-medium text-slate-800 dark:text-slate-200">
                {ind.name}
              </td>
              <td className="px-4 py-2 text-slate-600 dark:text-slate-300">
                {Object.entries(ind.params)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(", ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
