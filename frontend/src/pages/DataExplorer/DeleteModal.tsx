import { useState } from "react";

import { Trash2, X } from "lucide-react";

import { deleteData } from "../../services/dataApi";
import type { DataGroupSummary } from "../../types/data";

export default function DeleteModal({
  groups,
  onClose,
  onDeleted,
}: {
  groups: DataGroupSummary[];
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const first = groups[0];
  const count = groups.length;
  const totalCandles = groups.reduce((acc, g) => acc + g.total_candles, 0);
  const match = typed === first.symbol;

  const handleConfirm = async () => {
    if (!match || confirming) return;
    setConfirming(true);
    setError(null);
    const results = await Promise.allSettled(groups.map((g) => deleteData(g.symbol, g.timeframe)));
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed === 0) {
      onDeleted();
      return;
    }
    setError(`No se pudieron eliminar ${failed} combinacion${failed === 1 ? "" : "es"}.`);
    setConfirming(false);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-800">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Eliminar datos</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-4 px-5 py-4">
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            <p>
              {count === 1 ? (
                <>
                  <span className="font-semibold">{first.symbol}</span> · {first.timeframe}
                </>
              ) : (
                <span className="font-semibold">{count} combinaciones seleccionadas</span>
              )}
            </p>
            <p className="mt-1">
              Se eliminarán{" "}
              <span className="font-semibold">{totalCandles.toLocaleString("es")}</span> velas. Esta
              acción no se puede deshacer.
            </p>
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Escribe{" "}
              <span className="font-mono font-semibold text-slate-700 dark:text-slate-200">
                {first.symbol}
              </span>{" "}
              {count > 1 ? "(primera de las seleccionadas) " : ""}para confirmar
            </span>
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-rose-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>
          {error && (
            <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
              {error}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={!match || confirming}
            onClick={() => void handleConfirm()}
            className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-40"
          >
            <Trash2 className="h-4 w-4" />
            {confirming ? "Eliminando..." : `Eliminar ${totalCandles.toLocaleString("es")} velas`}
          </button>
        </div>
      </div>
    </div>
  );
}
