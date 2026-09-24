import { useCallback, useEffect, useState } from "react";

import { ArrowDown, ArrowUp, ChevronsUpDown, Plus, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { DeleteJobModal } from "../../components/DataImport/DeleteJobModal";
import { StatusBadge } from "../../components/DataImport/StatusBadge";
import { deleteJob, deleteJobsBatch, listJobs, type JobListQuery } from "../../services/api";
import type { JobListItem } from "../../types/dataImport";
import { formatDateEs, formatDateTimeEs } from "../../utils/format";

const PAGE_SIZE = 20;

function isTerminal(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

export default function ImportList() {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>("");
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState<string>("");
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [modalOpen, setModalOpen] = useState(false);
  const [modalIds, setModalIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (q: JobListQuery) => {
    setLoading(true);
    try {
      const data = await listJobs(q);
      setJobs(data.jobs);
      setTotal(data.total);
      setError(null);
    } catch {
      setError("No se pudo cargar la lista de importaciones.");
    } finally {
      setLoading(false);
    }
  }, []);

  const buildQuery = useCallback(
    (): JobListQuery => ({
      status: status || undefined,
      symbol: symbol || undefined,
      timeframe: timeframe || undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
      page,
      page_size: PAGE_SIZE,
    }),
    [status, symbol, timeframe, sortBy, sortOrder, page],
  );

  useEffect(() => {
    void load(buildQuery());
  }, [load, buildQuery]);

  useEffect(() => {
    const hasLive = jobs.some((j) => !isTerminal(j.status));
    if (!hasLive) return;
    const timer = window.setInterval(() => {
      void load(buildQuery());
    }, 5000);
    return () => window.clearInterval(timer);
  }, [jobs, load, buildQuery]);

  const handleSort = (key: string) => {
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
      const allSelected = jobs.every((j) => prev.has(j.id));
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
        await deleteJob(modalIds[0]);
      } else {
        await deleteJobsBatch(modalIds);
      }
      setSelectedIds(new Set());
      closeDeleteModal();
      await load(buildQuery());
    } catch {
      setError("No se pudieron borrar los jobs.");
    } finally {
      setBusy(false);
    }
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Importación de Datos</h1>
            <p className="text-sm text-slate-500">
              {total} job{total === 1 ? "" : "s"} de importación desde Binance
            </p>
          </div>
          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <button
                type="button"
                onClick={() => openDeleteModal([...selectedIds])}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                Borrar seleccionados ({selectedIds.size})
              </button>
            )}
            <Link
              to="/import/new"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              <Plus className="h-4 w-4" />
              Nueva importación
            </Link>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Estado</span>
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
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
            <span className="mb-1 block text-xs font-medium text-slate-500">Símbolo</span>
            <input
              type="text"
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value);
                setPage(1);
              }}
              placeholder="BTCUSDT"
              className="w-full max-w-56 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Timeframe</span>
            <select
              value={timeframe}
              onChange={(e) => {
                setTimeframe(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
            >
              <option value="">Todos</option>
              <option value="1m">1m</option>
              <option value="5m">5m</option>
              <option value="15m">15m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
              <option value="1w">1w</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void load(buildQuery())}
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
                <th className="px-4 py-2.5">
                  <input
                    type="checkbox"
                    checked={jobs.length > 0 && jobs.every((j) => selectedIds.has(j.id))}
                    onChange={toggleSelectAll}
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
                <th className="px-4 py-2.5">Símbolos</th>
                <th className="px-4 py-2.5">Timeframes</th>
                <SortableTh
                  label="Período"
                  sortKey="date_from"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <th className="px-4 py-2.5">Modo</th>
                <SortableTh
                  label="I / U / S"
                  sortKey="total_candles_inserted"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                  className="text-right"
                />
                <SortableTh
                  label="Creado"
                  sortKey="created_at"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.length === 0 && !loading && (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-slate-500">
                    No hay importaciones registradas.
                  </td>
                </tr>
              )}
              {jobs.map((j) => (
                <tr key={j.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(j.id)}
                      onChange={() => toggleSelect(j.id)}
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="px-4 py-2.5">
                    <Link to={`/import/${j.id}`} className="font-medium text-indigo-600 hover:underline">
                      {j.symbols.join(", ")}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">{j.timeframes.join(", ")}</td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {formatDateEs(j.date_from)} → {formatDateEs(j.date_to)}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium capitalize text-slate-600">
                      {j.import_mode}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">
                    {j.total_candles_inserted.toLocaleString("es")} /{" "}
                    {j.total_candles_updated.toLocaleString("es")} /{" "}
                    {j.total_candles_skipped.toLocaleString("es")}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {formatDateTimeEs(j.created_at)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => openDeleteModal([j.id])}
                      disabled={busy}
                      className="rounded p-1 text-slate-400 hover:text-rose-600 disabled:opacity-40"
                      title="Borrar job"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-slate-500">
            Página {page} de {pages}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={page >= pages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40"
            >
              Siguiente
            </button>
          </div>
        </div>
        <DeleteJobModal
          open={modalOpen}
          jobIds={modalIds}
          onClose={closeDeleteModal}
          onConfirm={confirmDelete}
          busy={busy}
        />
      </div>
    </main>
  );
}

function SortableTh({
  label,
  sortKey,
  sortBy,
  sortOrder,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: string;
  sortBy: string;
  sortOrder: "asc" | "desc";
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sortBy === sortKey;
  return (
    <th className={`px-4 py-2.5 ${className}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 uppercase tracking-wide ${
          className === "text-right" ? "justify-end" : ""
        } ${active ? "text-slate-900" : "hover:text-slate-900"}`}
      >
        {label}
        {active ? (
          sortOrder === "asc" ? (
            <ArrowUp className="h-3.5 w-3.5" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5" />
          )
        ) : (
          <ChevronsUpDown className="h-3.5 w-3.5 opacity-40" />
        )}
      </button>
    </th>
  );
}