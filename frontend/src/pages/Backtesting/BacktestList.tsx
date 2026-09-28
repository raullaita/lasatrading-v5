import { useCallback, useEffect, useState } from "react";

import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { DeleteJobModal } from "../../components/ui/DeleteJobModal";
import { SortableTh } from "../../components/ui/SortableTh";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { deleteBacktest, deleteBacktestsBatch, getBacktests } from "../../services/backtestsApi";
import {
  BACKTEST_TERMINAL_STATUSES,
  type BacktestRunListItem,
  type BacktestRunStatus,
} from "../../types/backtesting";
import {
  formatDateTimeEs,
  formatMoney,
  formatPercent,
  formatRate,
  toNumber,
} from "../../utils/format";

/** Tope del backend en `GET /backtests` (`page_size` le=100). */
const PAGE_SIZE = 20;

/**
 * Columnas admitidas por la lista blanca de `sort_by` del router
 * (`SORTABLE_RUN_COLUMNS`). `status` y `win_rate` NO estan: pedir cualquiera
 * de las dos devuelve 400, asi que quedan como `<th>` plano.
 */
const SORTABLE = new Set([
  "created_at",
  "total_trades",
  "net_pnl",
  "total_return_pct",
  "max_drawdown_pct",
  "equity_final",
]);

export default function BacktestList() {
  const [runs, setRuns] = useState<BacktestRunListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<BacktestRunStatus | "">("");
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [modalOpen, setModalOpen] = useState(false);
  const [modalIds, setModalIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getBacktests({
        status: status || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        page,
        page_size: PAGE_SIZE,
      });
      setRuns(data.runs);
      setTotal(data.total);
      setError(null);
    } catch {
      setError("No se pudo cargar la lista de backtests.");
    } finally {
      setLoading(false);
    }
  }, [status, sortBy, sortOrder, page]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Solo sondea si hay algo vivo en la página actual. Un run completado ya no
   * va a cambiar; preguntarle cada 5 s sería gastar peticiones en nada.
   */
  useEffect(() => {
    const hasLive = runs.some((r) => !BACKTEST_TERMINAL_STATUSES.includes(r.status));
    if (!hasLive) return;
    const timer = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [runs, load]);

  const handleSort = (key: string) => {
    if (!SORTABLE.has(key)) return;
    if (sortBy === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortOrder(key === "created_at" ? "desc" : "asc");
    }
    setPage(1);
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds((prev) => {
      const allSelected = runs.length > 0 && runs.every((r) => prev.has(r.id));
      if (allSelected) return new Set();
      return new Set(runs.map((r) => r.id));
    });
  };

  const openDeleteModal = (ids: string[]) => {
    setModalIds(ids);
    setModalOpen(true);
  };

  const closeDeleteModal = () => {
    setModalOpen(false);
    setModalIds([]);
    setSelectedIds(new Set());
  };

  const confirmDelete = async () => {
    setBusy(true);
    try {
      if (modalIds.length === 1) {
        await deleteBacktest(modalIds[0]);
      } else {
        await deleteBacktestsBatch(modalIds);
      }
      closeDeleteModal();
      await load();
    } catch {
      setError("No se pudieron borrar los backtests.");
    } finally {
      setBusy(false);
    }
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const allSelected = runs.length > 0 && runs.every((r) => selectedIds.has(r.id));

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Backtesting</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {total} backtest{total === 1 ? "" : "s"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <button
                type="button"
                onClick={() => openDeleteModal([...selectedIds])}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:bg-slate-900 dark:hover:bg-rose-950/50"
              >
                <Trash2 className="h-4 w-4" />
                Borrar seleccionados ({selectedIds.size})
              </button>
            )}
            <Link
              to="/backtesting/new"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              <Plus className="h-4 w-4" />
              Nuevo backtest
            </Link>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Estado
            </span>
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as BacktestRunStatus | "");
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="">Todos</option>
              <option value="pending">Pendiente</option>
              <option value="processing">Procesando</option>
              <option value="completed">Completado</option>
              <option value="failed">Fallido</option>
              <option value="cancelled">Cancelado</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refrescar
          </button>
        </div>

        {error && (
          <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            {error}
          </p>
        )}

        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2.5">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    aria-label="Seleccionar todos los backtests de la página"
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </th>
                <th className="px-4 py-2.5 uppercase tracking-wide">Estado</th>
                <SortableTh
                  label="Operaciones"
                  sortKey="total_trades"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="PnL neto"
                  sortKey="net_pnl"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Retorno"
                  sortKey="total_return_pct"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <th className="px-4 py-2.5 uppercase tracking-wide">Win rate</th>
                <SortableTh
                  label="Drawdown"
                  sortKey="max_drawdown_pct"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Capital final"
                  sortKey="equity_final"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Creado"
                  sortKey="created_at"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <th className="px-4 py-2.5 text-right">Acción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {runs.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={10}
                    className="px-4 py-10 text-center text-slate-500 dark:text-slate-400"
                  >
                    No hay backtests registrados.
                  </td>
                </tr>
              )}
              {runs.map((r) => {
                const pnl = toNumber(r.net_pnl);
                const ret = toNumber(r.total_return_pct);
                return (
                  <tr key={r.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(r.id)}
                        onChange={() => toggleSelect(r.id)}
                        aria-label={`Seleccionar backtest del ${new Date(r.created_at).toLocaleString("es-ES")}`}
                        className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {r.total_trades.toLocaleString("es-ES")}
                    </td>
                    <td
                      className={`px-4 py-2.5 font-medium ${
                        pnl === null
                          ? "text-slate-400 dark:text-slate-500"
                          : pnl >= 0
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-rose-600 dark:text-rose-400"
                      }`}
                    >
                      {pnl === null ? "—" : `${pnl >= 0 ? "+" : ""}${formatMoney(r.net_pnl)}`}
                    </td>
                    <td
                      className={`px-4 py-2.5 ${
                        ret === null
                          ? "text-slate-400 dark:text-slate-500"
                          : ret >= 0
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-rose-600 dark:text-rose-400"
                      }`}
                    >
                      {ret === null ? "—" : formatPercent(r.total_return_pct)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {formatRate(r.win_rate)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {formatPercent(r.max_drawdown_pct)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {formatMoney(r.equity_final)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                      <Link
                        to={`/backtesting/runs/${r.id}`}
                        className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        {formatDateTimeEs(r.created_at)}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => openDeleteModal([r.id])}
                        disabled={busy}
                        className="rounded p-1 text-slate-400 hover:text-rose-600 disabled:opacity-40 dark:text-slate-500 dark:hover:text-rose-500"
                        title="Borrar backtest"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Página {page} de {pages}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={page >= pages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              Siguiente
            </button>
          </div>
        </div>

        <DeleteJobModal
          open={modalOpen}
          jobIds={modalIds}
          itemNoun="backtest"
          consequence="junto con sus operaciones, la curva de equity y sus logs. El escaneo origen no se toca"
          onClose={closeDeleteModal}
          onConfirm={() => void confirmDelete()}
          busy={busy}
        />
      </div>
    </main>
  );
}
