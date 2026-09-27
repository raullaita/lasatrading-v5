import { useCallback, useEffect, useState } from "react";

import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { DeleteJobModal } from "../../components/ui/DeleteJobModal";
import { SortableTh } from "../../components/ui/SortableTh";
import { StatusBadge } from "../../components/ui/StatusBadge";
import {
  deletePatternScan,
  deletePatternScansBatch,
  getPatternScans,
} from "../../services/patternsApi";
import { PATTERN_TERMINAL_STATUSES, type PatternScanJobListItem } from "../../types/patterns";
import { formatDateEs, formatDateTimeEs } from "../../utils/format";

/** Tope del backend en `GET /scans` (`page_size` le=100). */
const PAGE_SIZE = 20;

/** Columnas admitidas por la lista blanca de `sort_by` del router. */
const SORTABLE = new Set([
  "created_at",
  "status",
  "symbol",
  "timeframe",
  "processed_candles",
  "date_from",
  "date_to",
  "finished_at",
]);

export default function PatternList() {
  const [jobs, setJobs] = useState<PatternScanJobListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
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
      const data = await getPatternScans({
        status: status || undefined,
        symbol: symbol || undefined,
        timeframe: timeframe || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        page,
        page_size: PAGE_SIZE,
      });
      setJobs(data.jobs);
      setTotal(data.total);
      setError(null);
    } catch {
      setError("No se pudo cargar la lista de escaneos.");
    } finally {
      setLoading(false);
    }
  }, [status, symbol, timeframe, sortBy, sortOrder, page]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Solo sondea si hay algo vivo en la página actual.
   *
   * `PATTERN_TERMINAL_STATUSES` viene del módulo de tipos y no se re-declara
   * aquí: si el backend añade un estado final nuevo, la lista deja de preguntar
   * sola en vez de quedarse consultando un job muerto cada 5 s para siempre.
   */
  useEffect(() => {
    const hasLive = jobs.some((j) => !PATTERN_TERMINAL_STATUSES.includes(j.status));
    if (!hasLive) return;
    const timer = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [jobs, load]);

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
      const allSelected = jobs.length > 0 && jobs.every((j) => prev.has(j.id));
      if (allSelected) return new Set();
      return new Set(jobs.map((j) => j.id));
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
        await deletePatternScan(modalIds[0]);
      } else {
        await deletePatternScansBatch(modalIds);
      }
      closeDeleteModal();
      await load();
    } catch {
      setError("No se pudieron borrar los escaneos.");
    } finally {
      setBusy(false);
    }
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const allSelected = jobs.length > 0 && jobs.every((j) => selectedIds.has(j.id));

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              Detección de Patrones
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {total} escaneo{total === 1 ? "" : "s"}
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
              to="/patterns/occurrences"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Ver ocurrencias
            </Link>
            <Link
              to="/patterns/new"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              <Plus className="h-4 w-4" />
              Nuevo escaneo
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
                setStatus(e.target.value);
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
          <label className="block flex-1">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Símbolo
            </span>
            <input
              type="text"
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value);
                setPage(1);
              }}
              placeholder="BTCUSDT"
              className="w-full max-w-56 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Timeframe
            </span>
            <select
              value={timeframe}
              onChange={(e) => {
                setTimeframe(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="">Todos</option>
              <option value="1m">1m</option>
              <option value="5m">5m</option>
              <option value="15m">15m</option>
              <option value="30m">30m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
              <option value="1w">1w</option>
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
                    aria-label="Seleccionar todos los escaneos de la página"
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </th>
                <SortableTh
                  label="Estado"
                  sortKey="status"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Símbolo"
                  sortKey="symbol"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Timeframe"
                  sortKey="timeframe"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Período"
                  sortKey="date_from"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <th className="px-4 py-2.5">Patrones</th>
                <SortableTh
                  label="Progreso"
                  sortKey="processed_candles"
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
              {jobs.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={9}
                    className="px-4 py-10 text-center text-slate-500 dark:text-slate-400"
                  >
                    No hay escaneos registrados.
                  </td>
                </tr>
              )}
              {jobs.map((j) => {
                const live = !PATTERN_TERMINAL_STATUSES.includes(j.status);
                return (
                  <tr key={j.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(j.id)}
                        onChange={() => toggleSelect(j.id)}
                        aria-label={`Seleccionar escaneo de ${j.symbol}`}
                        className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={j.status} />
                    </td>
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/patterns/scans/${j.id}`}
                        className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        {j.symbol}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {j.timeframe}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {formatDateEs(j.date_from)} → {formatDateEs(j.date_to)}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="text-slate-600 dark:text-slate-300">
                        {j.patterns_config.length}
                      </span>
                      <span className="ml-1 text-xs text-slate-400 dark:text-slate-500">
                        {j.patterns_config
                          .map((p) => p.code.replace(/_.*$/, ""))
                          .filter((v, i, arr) => arr.indexOf(v) === i)
                          .join(", ") || "—"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                      {live ? (
                        <span className="text-xs">
                          {j.processed_candles.toLocaleString("es-ES")} /{" "}
                          {j.total_candles.toLocaleString("es-ES")}
                        </span>
                      ) : (
                        <span className="text-slate-400 dark:text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                      {formatDateTimeEs(j.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => openDeleteModal([j.id])}
                        disabled={busy}
                        className="rounded p-1 text-slate-400 hover:text-rose-600 disabled:opacity-40 dark:text-slate-500 dark:hover:text-rose-500"
                        title="Borrar escaneo"
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
          itemNoun="escaneo"
          consequence="junto con todas sus ocurrencias detectadas y sus logs. Las velas y los indicadores no se tocan"
          onClose={closeDeleteModal}
          onConfirm={() => void confirmDelete()}
          busy={busy}
        />
      </div>
    </main>
  );
}
