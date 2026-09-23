import { useEffect, useState } from "react";

import { Plus, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../../components/DataImport/StatusBadge";
import { listJobs, type JobListQuery } from "../../services/api";
import type { JobListItem } from "../../types/dataImport";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async (query: JobListQuery) => {
    setLoading(true);
    try {
      const data = await listJobs(query);
      setJobs(data.jobs);
      setTotal(data.total);
      setError(null);
    } catch {
      setError("No se pudo cargar la lista de importaciones.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load({ status: status || undefined, symbol: symbol || undefined, timeframe: timeframe || undefined, page, page_size: PAGE_SIZE });
  }, [status, symbol, timeframe, page]);

  useEffect(() => {
    const hasLive = jobs.some((j) => !isTerminal(j.status));
    if (!hasLive) return;
    const timer = window.setInterval(() => {
      void load({ status: status || undefined, symbol: symbol || undefined, page, page_size: PAGE_SIZE });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [jobs, status, symbol, page]);

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
          <Link
            to="/import/new"
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" />
            Nueva importación
          </Link>
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
            onClick={() => void load({ status: status || undefined, symbol: symbol || undefined, timeframe: timeframe || undefined, page, page_size: PAGE_SIZE })}
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
                <th className="px-4 py-2.5">Estado</th>
                <th className="px-4 py-2.5">Símbolos</th>
                <th className="px-4 py-2.5">Timeframes</th>
                <th className="px-4 py-2.5">Período</th>
                <th className="px-4 py-2.5">Modo</th>
                <th className="px-4 py-2.5 text-right">I / U / S</th>
                <th className="px-4 py-2.5">Creado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                    No hay importaciones registradas.
                  </td>
                </tr>
              )}
              {jobs.map((j) => (
                <tr key={j.id} className="hover:bg-slate-50">
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
                    {new Date(j.date_from).toLocaleDateString("es")} →{" "}
                    {new Date(j.date_to).toLocaleDateString("es")}
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
                    {new Date(j.created_at).toLocaleString("es")}
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
      </div>
    </main>
  );
}