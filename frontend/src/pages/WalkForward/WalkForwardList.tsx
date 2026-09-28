import { useCallback, useEffect, useState } from "react";

import { Loader2, Plus, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../../components/ui/StatusBadge";
import { getWalkForwards } from "../../services/walkForwardApi";
import type { WalkForwardRun, WalkForwardRunStatus } from "../../types/walkForward";
import { formatDateTimeEs, formatPercent, toNumber } from "../../utils/format";

/** Tope del backend en `GET /walk-forward/runs` (`page_size` le=100). */
const PAGE_SIZE = 20;

/**
 * Lista de walk-forwards.
 *
 * Una columna menos que la lista de backtests y una mas, y las dos son
 * deliberadas:
 *
 * - **Falta** la de win rate. Una sola configuracion no tiene win rate agregado
 *   que signifiquen nada: hay una por ventana OOS, y la media de win rates de
 *   ventanas con distinta duracion no es una cifra que se pueda leer.
 * - **Está** la de simulaciones, que es la que dice cuanto trabajo se ha hecho
 *   de verdad. Es el numero que la regla 4 del Contrato Estadistico exige
 *   publicar, y el que permite distinguir "estuvo dos minutos" de "estuvo dos
 *   minutos probando 1.800 cosas".
 *
 * La columna de resultado va en blanco mientras el run no ha terminado, y no
 * muestra un guion que parezca un cero: un informe a medias no tiene retorno, y
 * un `—` en la columna de la cifra es un dato, no una ausencia.
 */
export default function WalkForwardList() {
  const [runs, setRuns] = useState<WalkForwardRun[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<WalkForwardRunStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getWalkForwards(page, PAGE_SIZE);
      const filtrados = status ? data.runs.filter((run) => run.status === status) : data.runs;
      setRuns(filtrados);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar la lista");
    } finally {
      setLoading(false);
    }
  }, [page, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalPaginas = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Walk-forwards</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Informes de optimización out-of-sample. Cada uno dice cuántas combinaciones evaluó y
            guarda sus candidatas, incluidas las descartadas.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/walk-forward/new"
            className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white"
          >
            <Plus className="h-4 w-4" /> Nuevo
          </Link>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600 dark:text-slate-400">Estado</label>
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as WalkForwardRunStatus | "");
            setPage(1);
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
        >
          <option value="">Todos</option>
          <option value="pending">Pendiente</option>
          <option value="processing">En curso</option>
          <option value="completed">Completado</option>
          <option value="failed">Fallido</option>
          <option value="cancelled">Cancelado</option>
        </select>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left dark:bg-slate-800">
            <tr>
              <th className="px-2 py-2">Creado</th>
              <th className="px-2 py-2">Escaneo</th>
              <th className="px-2 py-2">Estado</th>
              <th className="px-2 py-2 text-right">Ventanas</th>
              <th className="px-2 py-2 text-right">Simulaciones</th>
              <th className="px-2 py-2 text-right">Retorno OOS</th>
              <th className="px-2 py-2 text-right">Duración</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="px-2 py-8 text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </td>
              </tr>
            )}
            {!loading && runs.length === 0 && (
              <tr>
                <td colSpan={7} className="px-2 py-8 text-center text-slate-500">
                  Todavía no hay walk-forwards.
                </td>
              </tr>
            )}
            {runs.map((run) => (
              <tr
                key={run.id}
                className="border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
              >
                <td className="px-2 py-2 whitespace-nowrap">
                  <Link
                    to={`/walk-forward/runs/${run.id}`}
                    className="text-blue-600 hover:underline"
                  >
                    {formatDateTimeEs(run.created_at)}
                  </Link>
                </td>
                <td className="px-2 py-2 whitespace-nowrap text-slate-500">
                  {run.config.symbol} {run.config.timeframe}
                </td>
                <td className="px-2 py-2">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-2 py-2 text-right tabular-nums">{run.windows}</td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {run.simulations.toLocaleString("es-ES")}
                </td>
                <td
                  className={`px-2 py-2 text-right tabular-nums ${
                    (toNumber(run.oos_return_pct) ?? 0) < 0
                      ? "text-red-600 dark:text-red-400"
                      : "text-emerald-600 dark:text-emerald-400"
                  }`}
                >
                  {run.status === "completed" ? formatPercent(run.oos_return_pct) : "—"}
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-slate-500">
                  {run.elapsed_ms !== null ? `${Math.round(run.elapsed_ms / 1000)} s` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPaginas > 1 && (
        <div className="flex items-center justify-between text-sm">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50 dark:border-slate-600"
          >
            Anterior
          </button>
          <span className="text-slate-500">
            Página {page} de {totalPaginas} · {total} informes
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPaginas, p + 1))}
            disabled={page === totalPaginas}
            className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50 dark:border-slate-600"
          >
            Siguiente
          </button>
        </div>
      )}
    </div>
  );
}
