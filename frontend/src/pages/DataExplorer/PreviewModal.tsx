import { useEffect, useState } from "react";

import { X } from "lucide-react";

import { previewData } from "../../services/dataApi";
import type { DataCandle } from "../../types/data";
import { formatDateTimeEs } from "../../utils/format";

export default function PreviewModal({
  symbol,
  timeframe,
  onClose,
}: {
  symbol: string;
  timeframe: string;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<DataCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void previewData(symbol, timeframe, 50)
      .then((data) => {
        if (active) setRows(data.rows);
      })
      .catch(() => {
        if (active) setError("No se pudieron cargar las velas.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [symbol, timeframe]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-lg font-bold text-slate-900">
            Preview {symbol} · {timeframe}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="overflow-auto">
          {loading && (
            <div className="p-10 text-center text-slate-500">
              Cargando velas...
            </div>
          )}
          {error && (
            <div className="p-6">
              <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                {error}
              </p>
            </div>
          )}
          {!loading && !error && (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5">Fecha</th>
                  <th className="px-4 py-2.5 text-right">Open</th>
                  <th className="px-4 py-2.5 text-right">High</th>
                  <th className="px-4 py-2.5 text-right">Low</th>
                  <th className="px-4 py-2.5 text-right">Close</th>
                  <th className="px-4 py-2.5 text-right">Volume</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.timestamp} className="hover:bg-slate-50">
                    <td className="px-4 py-2 text-slate-600">
                      {formatDateTimeEs(r.timestamp)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                      {r.open}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                      {r.high}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                      {r.low}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                      {r.close}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                      {r.volume}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-slate-200 px-5 py-3">
          <p className="text-sm text-slate-500">
            {loading ? "Cargando..." : `${rows.length} velas (últimas 50)`}
          </p>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}