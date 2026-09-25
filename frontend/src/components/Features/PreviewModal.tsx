import { useEffect, useState } from "react";

import { Loader2, X } from "lucide-react";

import { getFeatureJobPreview } from "../../services/featuresApi";
import type { FeaturePreviewRow } from "../../types/features";

const fmt = (v: number | null) =>
  v === null
    ? "—"
    : v.toLocaleString("es-ES", { maximumFractionDigits: 8 });

export function PreviewModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const [rows, setRows] = useState<FeaturePreviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void getFeatureJobPreview(jobId, 100)
      .then((data) => {
        if (active) setRows(data.rows);
      })
      .catch(() => {
        if (active) setError("No se pudieron cargar los datos del cálculo.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  const uniqueIndicators = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row.indicators).forEach((name) => uniqueIndicators.add(name));
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-800">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Datos calculados ({rows.length})
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
            </div>
          ) : error ? (
            <p className="px-5 py-10 text-center text-sm text-rose-600 dark:text-rose-400">{error}</p>
          ) : rows.length === 0 ? (
            <p className="px-5 py-10 text-center text-sm text-slate-500 dark:text-slate-400">
              Sin datos calculados para este job.
            </p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-slate-500 uppercase dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-2">Timestamp</th>
                  <th className="px-4 py-2 text-right">Open</th>
                  <th className="px-4 py-2 text-right">High</th>
                  <th className="px-4 py-2 text-right">Low</th>
                  <th className="px-4 py-2 text-right">Close</th>
                  <th className="px-4 py-2 text-right">Volume</th>
                  {Array.from(uniqueIndicators).map((name) => (
                    <th key={name} className="px-4 py-2 text-right">
                      {name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td className="px-4 py-1.5 tabular-nums text-slate-600 dark:text-slate-300">
                      {new Date(row.timestamp).toLocaleString("es")}
                    </td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(row.open)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(row.high)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(row.low)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(row.close)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums text-slate-500 dark:text-slate-400">
                      {fmt(row.volume)}
                    </td>
                    {Array.from(uniqueIndicators).map((name) => (
                      <td key={name} className="px-4 py-1.5 text-right tabular-nums">
                        {row.indicators[name] !== undefined ? row.indicators[name].toFixed(4) : "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}