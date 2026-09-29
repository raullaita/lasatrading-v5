import { useCallback, useEffect, useMemo, useState } from "react";

import { AlertTriangle, Ban, Loader2, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { OosEquityChart } from "../../components/WalkForward/OosEquityChart";
import { WalkForwardLogViewer } from "../../components/WalkForward/WalkForwardLogViewer";
import { VerdictBadge } from "../../components/WalkForward/VerdictBadge";
import {
  PageHeader,
  PageShell,
  cardClass,
  errorClass,
  secondaryButtonClass,
  tableBodyClass,
  tableCellClass,
  tableClass,
  tableHeadCellClass,
  tableHeadClass,
} from "../../components/ui/PageShell";
import {
  cancelWalkForward,
  getWalkForwardEquity,
  getWalkForwardReport,
} from "../../services/walkForwardApi";
import { connectWalkForwardLogs } from "../../services/walkForwardWebSocket";
import type {
  WalkForwardLog,
  WalkForwardReport,
  WalkForwardVerdict,
} from "../../types/walkForward";
import { formatDateTimeEs, formatPercent, toNumber } from "../../utils/format";
import { etiquetaCandidata, etiquetaEstrategia } from "./coste";

/**
 * Informe de un walk-forward.
 *
 * Tres bloques y un orden que es el del usuario y no el del algoritmo: primero
 * **la conclusión**, después **la curva**, después **la tabla de candidatas** y
 * al final **la de ventanas**.
 *
 * La de ventanas va la última a propósito aunque se lea antes: es la
 * comprobación. Ponerla arriba invita a mirar el detalle antes de mirar el
 * veredicto, y el detalle sin el veredicto es un número sin contexto.
 */

/**
 * El IC95% con su propio formato y su propio color.
 *
 * Un intervalo metido en una celda de porcentaje con signo se lee como dos cifras
 * sueltas: `[-41,20, 318,75]` no parece un intervalo de unus. Se escribe
 * `[desde ; hasta]%`.
 *
 * Y el color **no** es decorativo: un intervalo que incluye el cero y uno que no
 * lo incluyen son afirmaciones distintas sobre lo mismo, y verlas del mismo
 * color haría que la columna pareciera decir algo que no dice.
 */
function FormatoIC({ low, high }: { low: string | null; high: string | null }) {
  if (low === null || high === null) {
    return (
      <span className="text-slate-400" title="Esta candidata se descartó sin muestra suficiente para un intervalo">
        —
      </span>
    );
  }
  const desde = toNumber(low);
  const hasta = toNumber(high);
  if (desde === null || hasta === null) return <span>—</span>;
  const cruza = desde <= 0 && hasta >= 0;
  return (
    <span
      className={
        cruza
          ? "text-amber-600 dark:text-amber-400"
          : "text-emerald-600 dark:text-emerald-400"
      }
      title={
        cruza
          ? "El intervalo incluye el cero: no se puede afirmar que gane"
          : "El intervalo excluye el cero"
      }
    >
      [{desde < 0 ? "" : " "}
      {desde.toFixed(1)} ; {hasta.toFixed(1)}]%
    </span>
  );
}

const TEXTO_VERDICT: Record<WalkForwardVerdict, string> = {
  sostenida:
    "Pasa todas las guardas, el intervalo de confianza excluye el cero y se ha evaluado en tres regímenes o más. Es el único veredicto que dice algo sobre más de un mercado.",
  prometedora:
    "Pasa todas las guardas, pero el intervalo de confianza incluye el cero: el resultado es compatible con haber sido azar. Merece una segunda mirada, no una decisión.",
  descartada:
    "No pasa las guardas duras. El motivo está en cada fila: sin operaciones, sin ventanas suficientes, o sin superar al mercado.",
};

export default function WalkForwardDetail() {
  const { runId = "" } = useParams();
  const [report, setReport] = useState<WalkForwardReport | null>(null);
  const [equity, setEquity] = useState<Awaited<
    ReturnType<typeof getWalkForwardEquity>
  > | null>(null);
  const [logs, setLogs] = useState<WalkForwardLog[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [canceling, setCanceling] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const data = await getWalkForwardReport(runId);
      setReport(data);
      setError(null);
      setEquity(await getWalkForwardEquity(runId, 1500));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el informe");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  useEffect(() => {
    if (!runId) return;
    return connectWalkForwardLogs(runId, {
      onLog: (log) => setLogs((previos) => [...previos, log]),
      onConnectionChange: setConnected,
      onError: setError,
    });
  }, [runId]);

  /**
   * Mientras el run siga vivo el informe cambia. Se recarga cuando llega la
   * línea que cierra el progreso, y no con un temporizador: recargar cada dos
   * segundos desperdicia peticiones y además puede pintar un informe que ya no es
   * el último.
   */
  useEffect(() => {
    if (!report) return;
    if (report.run.status === "completed" || report.run.status === "cancelled") return;
    const ultimo = logs[logs.length - 1];
    if (ultimo?.progress === 100 || ultimo?.level === "error") void cargar();
  }, [logs, report, cargar]);

  const candidatas = report?.candidates ?? [];
  const mejor = candidatas[0] ?? null;
  const progreso = logs.reduce<number | null>(
    (max, log) => (log.progress === null ? max : Math.max(max ?? 0, log.progress)),
    null,
  );
  const enCurso =
    report?.run.status === "pending" || report?.run.status === "processing";

  const edgeGlobal = useMemo(() => {
    const estrategia = toNumber(report?.run.oos_return_pct);
    const mercado = toNumber(report?.run.market_return_pct);
    if (estrategia === null || mercado === null) return null;
    return estrategia - mercado;
  }, [report]);

  const cancelar = async () => {
    setCanceling(true);
    try {
      await cancelWalkForward(runId);
      await cargar();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar");
    } finally {
      setCanceling(false);
    }
  };

  if (loading) {
    return (
      <PageShell>
        <p className="flex items-center gap-2 text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando informe…
        </p>
      </PageShell>
    );
  }

  if (!report) {
    return (
      <PageShell>
        <PageHeader title="Walk-forward" />
        <p className={errorClass}>{error ?? "Informe no encontrado"}</p>
        <Link to="/walk-forward" className={secondaryButtonClass}>
          Volver a la lista
        </Link>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={`${report.run.config.symbol} ${report.run.config.timeframe}`}
        subtitle={
          <>
            {report.run.windows} ventanas ·{" "}
            <strong>{report.run.simulations.toLocaleString("es-ES")} simulaciones</strong>{" "}
            evaluadas ·{" "}
            {report.run.elapsed_ms !== null
              ? `${Math.round(report.run.elapsed_ms / 1000)} s`
              : "sin medir"}
            {report.run.windows_without_selection > 0 && (
              <> · {report.run.windows_without_selection} sin selección posible</>
            )}
          </>
        }
        actions={
          <>
            {enCurso && (
              <button
                type="button"
                onClick={() => void cancelar()}
                disabled={canceling}
                className={secondaryButtonClass}
              >
                {canceling ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Ban className="h-4 w-4" />
                )}
                Cancelar
              </button>
            )}
            <button type="button" onClick={() => void cargar()} className={secondaryButtonClass}>
              <RefreshCw className="h-4 w-4" />
              Recargar
            </button>
            <Link to="/walk-forward" className={secondaryButtonClass}>
              Volver
            </Link>
          </>
        }
      />

      {error && <p className={errorClass}>{error}</p>}

      {enCurso && (
        <div className="mb-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-900 dark:bg-indigo-950/40">
          <p className="text-sm font-medium text-indigo-900 dark:text-indigo-200">
            {connected
              ? `En marcha${progreso !== null && ` · ${progreso}%`}`
              : "En marcha · reconectando con el progreso"}
          </p>
          {report.run.status === "pending" && (
            <p className="mt-1 text-xs text-indigo-700 dark:text-indigo-300">
              El informe no se puede leer hasta que termine: uno a medias no es un
              informe con menos filas, es uno cuyo veredicto no significa nada.
            </p>
          )}
        </div>
      )}

      {report.run.status === "cancelled" && (
        <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          Cancelado. El motor para en la frontera de la ventana siguiente, así que
          no hay informe a medias: o no hay informe, o hay uno completo.
        </div>
      )}

      {report.run.status === "failed" && (
        <div className={errorClass}>
          <p className="font-medium">El walk-forward falló</p>
          {report.run.error_message && (
            <p className="mt-1 whitespace-pre-line">{report.run.error_message}</p>
          )}
        </div>
      )}

      {report.run.status === "completed" && (
        <>
          {/* La conclusión, arriba del todo y con su texto. */}
          <section className={`${cardClass} mb-4 p-4`}>
            <div className="flex flex-wrap items-center gap-3">
              <VerdictBadge verdict={mejor?.verdict ?? "descartada"} />
              <span className="text-sm text-slate-600 dark:text-slate-400">
                La mejor de {candidatas.length} candidatas
                {mejor ? `: ${etiquetaCandidata(mejor)}` : ""}
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              {TEXTO_VERDICT[mejor?.verdict ?? "descartada"]}
            </p>
            {report.run.config.regimes_declared < 3 && (
              <p className="mt-2 flex items-start gap-2 text-sm text-amber-700 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                Evaluado sobre {report.run.config.regimes_declared}{" "}
                {report.run.config.regimes_declared === 1 ? "régimen" : "regímenes"}.{" "}
                «Sostenida» exige tres, así que con menos el techo es
                «prometedora» aunque el intervalo excluya el cero.
              </p>
            )}
            <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { t: "Retorno OOS", v: formatPercent(report.run.oos_return_pct) },
                { t: "Mercado OOS", v: formatPercent(report.run.market_return_pct) },
                {
                  t: "Diferencia",
                  v: edgeGlobal === null ? "—" : formatPercent(String(edgeGlobal)),
                  tono:
                    edgeGlobal !== null && edgeGlobal < 0
                      ? "text-rose-600 dark:text-rose-400"
                      : "text-emerald-600 dark:text-emerald-400",
                },
                { t: "Drawdown máx.", v: formatPercent(report.run.max_drawdown_pct) },
              ].map((k) => (
                <div key={k.t} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {k.t}
                  </dt>
                  <dd className={`mt-1 text-xl font-bold tabular-nums ${k.tono ?? ""}`}>
                    {k.v}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          {/* La curva. */}
          <section className={`${cardClass} mb-4 p-4`}>
            <h2 className="mb-3 font-semibold text-slate-900 dark:text-slate-100">
              Curva OOS encadenada frente al mercado
            </h2>
            <OosEquityChart points={equity?.points ?? []} />
            {equity && equity.total_points > equity.returned && (
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                Mostrando {equity.returned} de{" "}
                {equity.total_points.toLocaleString("es-ES")} velas, submuestreadas
                conservando los extremos y el cierre final.
              </p>
            )}
          </section>

          {/* Las candidatas, con el IC en su propia columna. */}
          <section className="mb-4">
            <h2 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">
              Candidatas ({candidatas.length})
            </h2>
            <div className={tableClass}>
              <table className="w-full text-left text-sm">
                <thead className={tableHeadClass}>
                  <tr>
                    <th className={tableHeadCellClass}>#</th>
                    <th className={tableHeadCellClass}>Combinación</th>
                    <th className={tableHeadCellClass}>Veredicto</th>
                    <th className={`${tableHeadCellClass} text-right`}>Score</th>
                    <th className={`${tableHeadCellClass} text-right`}>OOS</th>
                    <th className={`${tableHeadCellClass} text-right`}>Mercado</th>
                    <th className={`${tableHeadCellClass} text-right`}>IC95%</th>
                    <th className={`${tableHeadCellClass} text-right`}>Ops</th>
                    <th className={`${tableHeadCellClass} text-right`}>Sharpe</th>
                    <th className={`${tableHeadCellClass} text-right`}>DD máx.</th>
                    <th className={`${tableHeadCellClass} text-right`}>Supera</th>
                  </tr>
                </thead>
                <tbody className={tableBodyClass}>
                  {candidatas.map((c) => (
                    <tr key={c.rank} className="align-top">
                      <td className={`${tableCellClass} tabular-nums text-slate-400`}>
                        {c.rank}
                      </td>
                      <td className={`${tableCellClass} whitespace-nowrap font-medium`}>
                        {etiquetaCandidata(c)}
                      </td>
                      <td className={tableCellClass}>
                        <VerdictBadge verdict={c.verdict} />
                        {c.rejections.length > 0 && (
                          <ul className="mt-1 list-inside list-disc text-xs text-slate-500 dark:text-slate-400">
                            {c.rejections.map((m) => (
                              <li key={m}>{m}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td className={`${tableCellClass} text-right tabular-nums`}>
                        {toNumber(c.score)?.toFixed(1) ?? "—"}
                      </td>
                      <td
                        className={`${tableCellClass} text-right font-medium tabular-nums ${
                          (toNumber(c.oos_return_pct) ?? 0) < 0
                            ? "text-rose-600 dark:text-rose-400"
                            : "text-emerald-600 dark:text-emerald-400"
                        }`}
                      >
                        {formatPercent(c.oos_return_pct)}
                      </td>
                      <td className={`${tableCellClass} text-right tabular-nums text-slate-500`}>
                        {formatPercent(c.market_return_pct)}
                      </td>
                      <td className={`${tableCellClass} whitespace-nowrap text-right tabular-nums`}>
                        <FormatoIC low={c.ci95_low} high={c.ci95_high} />
                      </td>
                      <td className={`${tableCellClass} text-right tabular-nums`}>
                        {c.trades}
                      </td>
                      <td className={`${tableCellClass} text-right tabular-nums`}>
                        {toNumber(c.sharpe_mean)?.toFixed(2) ?? "—"}
                      </td>
                      <td className={`${tableCellClass} text-right tabular-nums`}>
                        {formatPercent(c.max_drawdown_worst)}
                      </td>
                      <td className={`${tableCellClass} text-right tabular-nums`}>
                        {c.beats_market_windows}/{c.windows}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Las ventanas, la comprobación, y por eso al final. */}
          <section className="mb-4">
            <h2 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">
              Ventanas ({report.windows.length})
            </h2>
            <p className="mb-2 text-sm text-slate-500 dark:text-slate-400">
              La tabla que permite ver que el resultado no viene de una ventana
              suelta. La diferencia con el mercado se calcula al pintar: es una
              resta de dos columnas que ya están.
            </p>
            <div className={tableClass}>
              <table className="w-full text-left text-sm">
                <thead className={tableHeadClass}>
                  <tr>
                    <th className={tableHeadCellClass}>#</th>
                    <th className={tableHeadCellClass}>In-sample</th>
                    <th className={tableHeadCellClass}>Out-of-sample</th>
                    <th className={tableHeadCellClass}>Elegida en el IS</th>
                    <th className={`${tableHeadCellClass} text-right`}>Ops</th>
                    <th className={`${tableHeadCellClass} text-right`}>OOS</th>
                    <th className={`${tableHeadCellClass} text-right`}>Mercado</th>
                    <th className={`${tableHeadCellClass} text-right`}>Diferencia</th>
                    <th className={`${tableHeadCellClass} text-right`}>Sharpe</th>
                    <th className={`${tableHeadCellClass} text-right`}>DD</th>
                  </tr>
                </thead>
                <tbody className={tableBodyClass}>
                  {report.windows.map((v) => {
                    const dif =
                      (toNumber(v.oos_return_pct) ?? 0) - (toNumber(v.market_return_pct) ?? 0);
                    return (
                      <tr key={v.index}>
                        <td className={`${tableCellClass} tabular-nums text-slate-400`}>
                          {v.index}
                        </td>
                        <td className={`${tableCellClass} whitespace-nowrap text-slate-500`}>
                          {formatDateTimeEs(v.is_from)} → {formatDateTimeEs(v.is_to)}
                        </td>
                        <td className={`${tableCellClass} whitespace-nowrap text-slate-500`}>
                          {formatDateTimeEs(v.oos_from)} → {formatDateTimeEs(v.oos_to)}
                        </td>
                        <td className={`${tableCellClass} whitespace-nowrap font-medium`}>
                          {etiquetaEstrategia(v.selected_strategy)}
                        </td>
                        <td className={`${tableCellClass} text-right tabular-nums`}>
                          {v.oos_trades}
                        </td>
                        <td className={`${tableCellClass} text-right tabular-nums`}>
                          {formatPercent(v.oos_return_pct)}
                        </td>
                        <td className={`${tableCellClass} text-right tabular-nums text-slate-500`}>
                          {formatPercent(v.market_return_pct)}
                        </td>
                        <td
                          className={`${tableCellClass} text-right font-medium tabular-nums ${
                            dif < 0
                              ? "text-rose-600 dark:text-rose-400"
                              : "text-emerald-600 dark:text-emerald-400"
                          }`}
                        >
                          {formatPercent(String(dif))}
                        </td>
                        <td className={`${tableCellClass} text-right tabular-nums`}>
                          {toNumber(v.oos_sharpe)?.toFixed(2) ?? "—"}
                        </td>
                        <td className={`${tableCellClass} text-right tabular-nums`}>
                          {formatPercent(v.oos_max_drawdown_pct)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <section>
        <h2 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">Progreso</h2>
        <WalkForwardLogViewer logs={logs} connected={connected} />
      </section>
    </PageShell>
  );
}
