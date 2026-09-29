import { useCallback, useEffect, useState } from "react";

import { Loader2, Plus, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../../components/ui/StatusBadge";
import {
  EmptyRow,
  Field,
  FilterBar,
  PageHeader,
  PageShell,
  errorClass,
  inputClass,
  primaryButtonClass,
  secondaryButtonClass,
  tableBodyClass,
  tableCellClass,
  tableClass,
  tableHeadCellClass,
  tableHeadClass,
} from "../../components/ui/PageShell";
import { getWalkForwards } from "../../services/walkForwardApi";
import type {
  WalkForwardRun,
  WalkForwardRunStatus,
} from "../../types/walkForward";
import { formatDateTimeEs, formatPercent, toNumber } from "../../utils/format";

/** Tope del backend en `GET /walk-forward/runs` (`page_size` le=100). */
const PAGE_SIZE = 20;

/**
 * Lista de walk-forwards.
 *
 * Dos columnas menos que la de backtests y una más, y las dos son deliberadas:
 *
 * - **Falta** la de win rate. Una sola configuración no tiene win rate agregado
 *   que signifique nada: hay uno por ventana OOS, y la media de ventanas con
 *   distinta duración y distinto número de operaciones es una cifra que no se
 *   puede leer.
 * - **Está** la de simulaciones, que es la que dice cuánto trabajo se ha hecho
 *   de verdad. Es el número que la regla 4 del Contrato Estadístico exige
 *   publicar, y el que permite distinguir "estuvo dos minutos" de "estuvo dos
 *   minutos probando 1.800 cosas".
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
      setRuns(status ? data.runs.filter((r) => r.status === status) : data.runs);
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
    <PageShell>
      <PageHeader
        title="Walk-forward"
        subtitle={
          <>
            {total} informe{total === 1 ? "" : "s"}. Cada uno dice cuántas
            combinaciones evaluó y guarda sus candidatas, incluidas las
            descartadas.
          </>
        }
        actions={
          <>
            <Link to="/walk-forward/new" className={primaryButtonClass}>
              <Plus className="h-4 w-4" />
              Nuevo walk-forward
            </Link>
            <button
              type="button"
              onClick={() => void load()}
              className={secondaryButtonClass}
              aria-label="Refrescar"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refrescar
            </button>
          </>
        }
      />

      <FilterBar>
        <Field label="Estado">
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as WalkForwardRunStatus | "");
              setPage(1);
            }}
            className={inputClass}
          >
            <option value="">Todos</option>
            <option value="pending">Pendiente</option>
            <option value="processing">En curso</option>
            <option value="completed">Completado</option>
            <option value="failed">Fallido</option>
            <option value="cancelled">Cancelado</option>
          </select>
        </Field>
      </FilterBar>

      {error && <p className={errorClass}>{error}</p>}

      <div className={tableClass}>
        <table className="w-full text-left text-sm">
          <thead className={tableHeadClass}>
            <tr>
              <th className={tableHeadCellClass}>Creado</th>
              <th className={tableHeadCellClass}>Escaneo</th>
              <th className={tableHeadCellClass}>Estado</th>
              <th className={`${tableHeadCellClass} text-right`}>Ventanas</th>
              <th className={`${tableHeadCellClass} text-right`}>Simulaciones</th>
              <th className={`${tableHeadCellClass} text-right`}>Retorno OOS</th>
              <th className={`${tableHeadCellClass} text-right`}>Duración</th>
            </tr>
          </thead>
          <tbody className={tableBodyClass}>
            {loading && runs.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </td>
              </tr>
            )}
            {!loading && runs.length === 0 && (
              <EmptyRow colSpan={7}>No hay walk-forwards.</EmptyRow>
            )}
            {runs.map((run) => {
              const retorno = toNumber(run.oos_return_pct);
              return (
                <tr key={run.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className={`${tableCellClass} whitespace-nowrap`}>
                    <Link
                      to={`/walk-forward/runs/${run.id}`}
                      className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                    >
                      {formatDateTimeEs(run.created_at)}
                    </Link>
                  </td>
                  <td className={`${tableCellClass} whitespace-nowrap text-slate-600 dark:text-slate-400`}>
                    {run.config.symbol} {run.config.timeframe}
                  </td>
                  <td className={tableCellClass}>
                    <StatusBadge status={run.status} />
                  </td>
                  <td className={`${tableCellClass} text-right tabular-nums`}>
                    {run.windows}
                  </td>
                  <td className={`${tableCellClass} text-right tabular-nums`}>
                    {run.simulations.toLocaleString("es-ES")}
                  </td>
                  <td
                    className={`${tableCellClass} text-right font-medium tabular-nums ${
                      (retorno ?? 0) < 0
                        ? "text-rose-600 dark:text-rose-400"
                        : "text-emerald-600 dark:text-emerald-400"
                    }`}
                  >
                    {/* En blanco mientras el run no termina: un guion con el
                        mismo aspecto que un cero se lee como un cero. */}
                    {run.status === "completed" ? formatPercent(run.oos_return_pct) : "—"}
                  </td>
                  <td className={`${tableCellClass} text-right tabular-nums text-slate-500`}>
                    {run.elapsed_ms !== null ? `${Math.round(run.elapsed_ms / 1000)} s` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {totalPaginas > 1 && (
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className={secondaryButtonClass}
          >
            Anterior
          </button>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            Página {page} de {totalPaginas}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPaginas, p + 1))}
            disabled={page === totalPaginas}
            className={secondaryButtonClass}
          >
            Siguiente
          </button>
        </div>
      )}
    </PageShell>
  );
}
