import { useCallback, useEffect, useState } from "react";

import { Eye, RefreshCw, Trash2 } from "lucide-react";

import { getDataSummary } from "../../services/dataApi";
import type { DataGroupSummary } from "../../types/data";
import { formatDateEs } from "../../utils/format";
import DeleteModal from "./DeleteModal";
import PreviewModal from "./PreviewModal";

export default function DataExplorer() {
  const [groups, setGroups] = useState<DataGroupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewTarget, setPreviewTarget] = useState<DataGroupSummary | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<DataGroupSummary | null>(
    null,
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getDataSummary();
      setGroups(data.groups);
      setError(null);
    } catch {
      setError("No se pudo cargar el resumen de datos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totalCandles = groups.reduce((acc, g) => acc + g.total_candles, 0);

  const handleDeleted = () => {
    setDeleteTarget(null);
    void load();
  };

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              Explorador de Datos
            </h1>
            <p className="text-sm text-slate-500">
              {groups.length} combinacione{groups.length === 1 ? "" : "s"} y{" "}
              {totalCandles.toLocaleString("es")} velas en la base de datos
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refrescar
          </button>
        </div>

        {error && (
          <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            {error}
          </p>
        )}

        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2.5">Símbolo</th>
                <th className="px-4 py-2.5">Timeframe</th>
                <th className="px-4 py-2.5 text-right">Total velas</th>
                <th className="px-4 py-2.5">Primera vela</th>
                <th className="px-4 py-2.5">Última vela</th>
                <th className="px-4 py-2.5 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {groups.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-10 text-center text-slate-500"
                  >
                    No hay datos OHLCV en la base de datos.
                  </td>
                </tr>
              )}
              {groups.map((g) => (
                <tr key={`${g.symbol}-${g.timeframe}`} className="hover:bg-slate-50">
                  <td className="px-4 py-2.5 font-medium text-slate-900">
                    {g.symbol}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                      {g.timeframe}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">
                    {g.total_candles.toLocaleString("es")}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {formatDateEs(g.first_timestamp)}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {formatDateEs(g.last_timestamp)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="inline-flex gap-2">
                      <button
                        type="button"
                        onClick={() => setPreviewTarget(g)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        Ver
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(g)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Eliminar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {previewTarget && (
        <PreviewModal
          symbol={previewTarget.symbol}
          timeframe={previewTarget.timeframe}
          onClose={() => setPreviewTarget(null)}
        />
      )}
      {deleteTarget && (
        <DeleteModal
          group={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={handleDeleted}
        />
      )}
    </main>
  );
}