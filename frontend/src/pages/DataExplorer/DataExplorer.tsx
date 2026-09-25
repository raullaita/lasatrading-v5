import { useCallback, useEffect, useMemo, useState } from "react";

import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { SortableTh } from "../../components/ui/SortableTh";
import { getDataSummary } from "../../services/dataApi";
import type { DataGroupSummary } from "../../types/data";
import { formatDateEs } from "../../utils/format";
import DeleteModal from "./DeleteModal";
import PreviewModal from "./PreviewModal";

const PAGE_SIZE = 20;

const groupKey = (g: DataGroupSummary) => `${g.symbol}|${g.timeframe}`;

type SortKey = "symbol" | "timeframe" | "total_candles" | "first_timestamp" | "last_timestamp";

export default function DataExplorer() {
  const [groups, setGroups] = useState<DataGroupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("symbol");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [previewTarget, setPreviewTarget] = useState<DataGroupSummary | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteGroups, setDeleteGroups] = useState<DataGroupSummary[]>([]);

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

  const filtered = useMemo(() => {
    const sym = symbol.trim().toLowerCase();
    return groups.filter((g) => {
      const symOk = !sym || g.symbol.toLowerCase().includes(sym);
      const tfOk = !timeframe || g.timeframe === timeframe;
      return symOk && tfOk;
    });
  }, [groups, symbol, timeframe]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortOrder === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "total_candles":
          cmp = a.total_candles - b.total_candles;
          break;
        case "first_timestamp":
          cmp = new Date(a.first_timestamp).getTime() - new Date(b.first_timestamp).getTime();
          break;
        case "last_timestamp":
          cmp = new Date(a.last_timestamp).getTime() - new Date(b.last_timestamp).getTime();
          break;
        default:
          cmp = a[sortBy].localeCompare(b[sortBy], "es", { sensitivity: "base" });
      }
      return cmp * dir;
    });
    return arr;
  }, [filtered, sortBy, sortOrder]);

  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const total = sorted.length;
  const totalCandles = filtered.reduce((acc, g) => acc + g.total_candles, 0);

  useEffect(() => {
    if (page > pages) setPage(pages);
  }, [page, pages]);

  const paginated = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSort = (key: string) => {
    if (sortBy === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key as SortKey);
      setSortOrder("asc");
    }
    setPage(1);
  };

  const toggleSelect = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const visibleKeys = paginated.map(groupKey);
    const allSelected = visibleKeys.every((key) => selectedKeys.has(key));
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      for (const key of visibleKeys) {
        if (allSelected) next.delete(key);
        else next.add(key);
      }
      return next;
    });
  };

  const openDelete = (groupList: DataGroupSummary[]) => {
    setDeleteGroups(groupList);
    setDeleteOpen(true);
  };

  const handleDeleted = () => {
    setDeleteOpen(false);
    setDeleteGroups([]);
    setSelectedKeys(new Set());
    void load();
  };

  const selectedGroups = groups.filter((g) => selectedKeys.has(groupKey(g)));

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              Explorador de Datos
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {total} combinacione{total === 1 ? "" : "s"} y{" "}
              {totalCandles.toLocaleString("es")} velas en la base de datos
            </p>
          </div>
          <div className="flex items-center gap-2">
            {selectedKeys.size > 0 && (
              <button
                type="button"
                onClick={() => openDelete(selectedGroups)}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:bg-slate-900 dark:hover:bg-rose-950/50"
              >
                <Trash2 className="h-4 w-4" />
                Borrar seleccionados ({selectedKeys.size})
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

        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
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
                    checked={paginated.length > 0 && paginated.every((g) => selectedKeys.has(groupKey(g)))}
                    onChange={toggleSelectAll}
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </th>
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
                  label="Total velas"
                  sortKey="total_candles"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                  className="text-right"
                />
                <SortableTh
                  label="Primera vela"
                  sortKey="first_timestamp"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
                <SortableTh
                  label="Última vela"
                  sortKey="last_timestamp"
                  sortBy={sortBy}
                  sortOrder={sortOrder}
                  onSort={handleSort}
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {paginated.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-500 dark:text-slate-400">
                    No hay datos OHLCV en la base de datos.
                  </td>
                </tr>
              )}
              {paginated.map((g) => (
                <tr key={groupKey(g)} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedKeys.has(groupKey(g))}
                      onChange={() => toggleSelect(groupKey(g))}
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() => setPreviewTarget(g)}
                      className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                    >
                      {g.symbol}
                    </button>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {g.timeframe}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600 dark:text-slate-300">
                    {g.total_candles.toLocaleString("es")}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                    {formatDateEs(g.first_timestamp)}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                    {formatDateEs(g.last_timestamp)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => openDelete([g])}
                      className="rounded p-1 text-slate-400 hover:text-rose-600 disabled:opacity-40 dark:text-slate-500 dark:hover:text-rose-500"
                      title="Eliminar datos"
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
      </div>

      {previewTarget && (
        <PreviewModal
          symbol={previewTarget.symbol}
          timeframe={previewTarget.timeframe}
          onClose={() => setPreviewTarget(null)}
        />
      )}
      {deleteOpen && (
        <DeleteModal
          groups={deleteGroups}
          onClose={() => setDeleteOpen(false)}
          onDeleted={handleDeleted}
        />
      )}
    </main>
  );
}