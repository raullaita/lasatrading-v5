import { useEffect, useState } from "react";

import { Loader2, X } from "lucide-react";

import { previewJob } from "../../services/api";
import type { ImportJobCombination, PreviewCandle } from "../../types/dataImport";

const fmt = (v: string) => Number(v).toLocaleString("es-ES", { maximumFractionDigits: 8 });

export function PreviewModal({
  jobId,
  combinations,
  onClose,
}: {
  jobId: string;
  combinations: ImportJobCombination[];
  onClose: () => void;
}) {
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [rows, setRows] = useState<PreviewCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void previewJob(jobId, { symbol: symbol || undefined, timeframe: timeframe || undefined, limit: 100 })
      .then((data) => {
        if (active) setRows(data.rows);
      })
      .catch(() => {
        if (active) setError("No se pudieron cargar las velas del job.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId, symbol, timeframe]);

  const symbols = [...new Set(combinations.map((c) => c.symbol))];
  const timeframes = [...new Set(combinations.map((c) => c.timeframe))];

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
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Velas importadas ({rows.length})</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex flex-wrap gap-3 border-b border-slate-100 px-5 py-3 dark:border-slate-800">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">Símbolo</span>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="">Todos</option>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">Timeframe</span>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="">Todos</option>
              {timeframes.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </label>
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
              Sin velas para los filtros seleccionados.
            </p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-slate-500 uppercase dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-2">Fecha (UTC)</th>
                  <th className="px-4 py-2">Símbolo</th>
                  <th className="px-4 py-2">TF</th>
                  <th className="px-4 py-2 text-right">Open</th>
                  <th className="px-4 py-2 text-right">High</th>
                  <th className="px-4 py-2 text-right">Low</th>
                  <th className="px-4 py-2 text-right">Close</th>
                  <th className="px-4 py-2 text-right">Volume</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((r) => (
                  <tr key={`${r.symbol}-${r.timeframe}-${r.timestamp}`}>
                    <td className="px-4 py-1.5 tabular-nums text-slate-600 dark:text-slate-300">
                      {new Date(r.timestamp).toLocaleString("es")}
                    </td>
                    <td className="px-4 py-1.5 font-medium text-slate-800 dark:text-slate-200">{r.symbol}</td>
                    <td className="px-4 py-1.5 text-slate-500 dark:text-slate-400">{r.timeframe}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(r.open)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(r.high)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(r.low)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums">{fmt(r.close)}</td>
                    <td className="px-4 py-1.5 text-right tabular-nums text-slate-500 dark:text-slate-400">{fmt(r.volume)}</td>
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