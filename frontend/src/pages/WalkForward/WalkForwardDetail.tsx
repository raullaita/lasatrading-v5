import { useCallback, useEffect, useMemo, useState } from "react";

import { AlertTriangle, Ban, Loader2, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { OosEquityChart } from "../../components/WalkForward/OosEquityChart";
import { WalkForwardLogViewer } from "../../components/WalkForward/WalkForwardLogViewer";
import { VerdictBadge } from "../../components/WalkForward/VerdictBadge";
import {
  cancelWalkForward,
  getWalkForwardEquity,
  getWalkForwardReport,
} from "../../services/walkForwardApi";
import { connectWalkForwardLogs } from "../../services/walkForwardWebSocket";
import { formatearIC, etiquetaCandidata, etiquetaEstrategia, TEXTO_VERDICT } from "./coste";
import type { WalkForwardLog, WalkForwardReport } from "../../types/walkForward";
import { formatDateEs, formatPercent, toNumber } from "../../utils/format";

/**
 * Informe de un walk-forward.
 *
 * Tres bloques y un orden que no es el de la spec:
 *
 * 1. **Veredicto arriba, con su texto.** No una etiqueta de color suelta: la
 *    etiqueta dice "prometedora" y no dice por que. El texto de la §5.2 es lo
 *    que convierte un color en un juicio, y sin el el usuario tiene que
 *    adivinar si el motor es optimista o@gmail.
 * 2. **La tabla de candidatas**, con el IC95% en su propia columna y en su
 *    propio formato. Es el numero que decide, y un IC metido en una celda de
 *    porcentaje con signo se lee mal: `[-41,20, 318,75]` son dos cifras, no un
 *    intervalo de unus.
 * 3. **La tabla de ventanas**, que es la que permite ver que el resultado no
 *    viene de una ventana suelta. Va despues a proposito, aunque se lea antes:
 *    es la comprobacion, y la comprobacion va despues de la cifra.
 */

/**
 * El IC95% en su celda, con el color que dice si el intervalo incluye el cero.
 *
 * El color no es decorativo: un intervalo que incluye el cero y uno que no lo
 * incluyen son afirmaciones distintas sobre lo mismo, y verlas en el mismo
 * color haria que la columna parece que dice algo que no dice. El formato en si
 * vive en `coste.ts`, que es donde se puede testear sin DOM.
 */
function FormatoIC({ low, high }: { low: string | null; high: string | null }) {
  const { texto, cruzaCero } = formatearIC(low, high);
  if (cruzaCero === null) return <span className="text-slate-400">{texto}</span>;
  return (
    <span
      className={
        cruzaCero ? "text-amber-700 dark:text-amber-300" : "text-emerald-700 dark:text-emerald-300"
      }
      title={
        cruzaCero
          ? "El intervalo incluye el cero: no se puede afirmar que gane"
          : "El intervalo excluye el cero"
      }
    >
      {texto}
    </span>
  );
}

export default function WalkForwardDetail() {
  const { runId = "" } = useParams();
  const [report, setReport] = useState<WalkForwardReport | null>(null);
  const [equity, setEquity] = useState<Awaited<ReturnType<typeof getWalkForwardEquity>> | null>(
    null,
  );
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
      const serie = await getWalkForwardEquity(runId, 1500);
      setEquity(serie);
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
   * Mientras el run siga vivo, el informe cambia. Se recarga cuando llega la
   * linea que cierra el progreso, y no con un temporizador: recargar cada dos
   * segundos desperdicia peticiones y ademas puede pisar el informe con una
   * respuesta que ya no es la ultima.
   */
  useEffect(() => {
    if (!report || report.run.status === "completed" || report.run.status === "cancelled") {
      return;
    }
    const ultimo = logs[logs.length - 1];
    if (ultimo?.progress === 100 || ultimo?.level === "error") void cargar();
  }, [logs, report, cargar]);

  const candidatas = report?.candidates ?? [];
  const mejor = candidatas[0] ?? null;
  const progreso = logs.reduce<number | null>(
    (max, log) => (log.progress === null ? max : Math.max(max ?? 0, log.progress)),
    null,
  );
  const enCurso = report?.run.status === "pending" || report?.run.status === "processing";

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
      <div className="flex items-center gap-2 p-8 text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Cargando informe…
      </div>
    );
  }

  if (error && !report) {
    return (
      <div className="space-y-4 p-4">
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </div>
        <Link to="/walk-forward" className="text-sm text-blue-600 hover:underline">
          Volver a la lista
        </Link>
      </div>
    );
  }

  if (!report) return null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">
            Walk-forward sobre {report.run.config.symbol} {report.run.config.timeframe}
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            {report.run.windows} ventanas ·{" "}
            <strong>{report.run.simulations.toLocaleString("es-ES")} simulaciones</strong> evaluadas
            ·{" "}
            {report.run.elapsed_ms !== null
              ? `${Math.round(report.run.elapsed_ms / 1000)} s`
              : "sin medir"}
            {report.run.windows_without_selection > 0 && (
              <> · {report.run.windows_without_selection} ventanas sin selección posible</>
            )}
          </p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Las {report.run.simulations.toLocaleString("es-ES")} simulaciones no se guardan una a
            una: son reproducibles desde la configuración congelada. Lo que se guarda son las{" "}
            {candidatas.length} candidatas, incluidas las descartadas.
          </p>
        </div>
        <div className="flex gap-2">
          {enCurso && (
            <button
              type="button"
              onClick={cancelar}
              disabled={canceling}
              className="inline-flex items-center gap-1 rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
            >
              {canceling ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Ban className="h-4 w-4" />
              )}
              Cancelar
            </button>
          )}
          <button
            type="button"
            onClick={() => void cargar()}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            <RefreshCw className="h-4 w-4" /> Recargar
          </button>
        </div>
      </header>

      {enCurso && (
        <div className="rounded border border-blue-300 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/40">
          <p className="flex items-center gap-2 text-sm text-blue-800 dark:text-blue-200">
            {connected ? (
              <span>En marcha{progreso !== null && ` · ventana ${progreso}%`}</span>
            ) : (
              "En marcha · reconectando con el progreso"
            )}
          </p>
          {report.run.status === "pending" && (
            <p className="mt-1 text-xs text-blue-700 dark:text-blue-300">
              El informe no se puede leer hasta que termine: un informe a medias no es un informe
              con menos filas, es uno cuyo veredicto no significa nada.
            </p>
          )}
        </div>
      )}

      {report.run.status === "cancelled" && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          Cancelado. El motor para en la frontera de la ventana siguiente, así que no hay informe a
          medias: o no hay informe, o hay uno completo.
        </div>
      )}

      {report.run.status === "failed" && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          <p className="font-medium">El walk-forward falló</p>
          {report.run.error_message && (
            <p className="mt-1 whitespace-pre-line">{report.run.error_message}</p>
          )}
        </div>
      )}

      {report.run.status === "completed" && (
        <>
          <section className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <VerdictBadge verdict={mejor?.verdict ?? "descartada"} />
              {mejor && (
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  La mejor de {candidatas.length} candidatas: {etiquetaCandidata(mejor)}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {TEXTO_VERDICT[mejor?.verdict ?? "descartada"]}
            </p>
            {report.run.config.regimes_declared < 3 && (
              <p className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                Evaluado sobre {report.run.config.regimes_declared}{" "}
                {report.run.config.regimes_declared === 1 ? "régimen" : "regímenes"}. «Sostenida»
                exige tres, así que con menos el techo del veredicto es «prometedora» aunque el
                intervalo de confianza excludes el cero.
              </p>
            )}

            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
                <dt className="text-xs uppercase text-slate-500 dark:text-slate-400">
                  Retorno OOS
                </dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {formatPercent(report.run.oos_return_pct)}
                </dd>
              </div>
              <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
                <dt className="text-xs uppercase text-slate-500 dark:text-slate-400">
                  Mercado OOS
                </dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {formatPercent(report.run.market_return_pct)}
                </dd>
              </div>
              <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
                <dt className="text-xs uppercase text-slate-500 dark:text-slate-400">Diferencia</dt>
                <dd
                  className={`mt-1 text-xl font-semibold tabular-nums ${
                    edgeGlobal !== null && edgeGlobal < 0
                      ? "text-red-600 dark:text-red-400"
                      : "text-emerald-600 dark:text-emerald-400"
                  }`}
                >
                  {edgeGlobal === null ? "—" : formatPercent(String(edgeGlobal))}
                </dd>
              </div>
              <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
                <dt className="text-xs uppercase text-slate-500 dark:text-slate-400">
                  Drawdown máximo
                </dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {formatPercent(report.run.max_drawdown_pct)}
                </dd>
              </div>
            </dl>
          </section>

          <section className="space-y-2">
            <h2 className="font-medium">Curva OOS encadenada frente al mercado</h2>
            <OosEquityChart points={equity?.points ?? []} />
            {equity && equity.total_points > equity.returned && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Mostrando {equity.returned} de {equity.total_points.toLocaleString("es-ES")} velas,
                submuestreadas conservando los extremos y el cierre final.
              </p>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="font-medium">Candidatas ({candidatas.length})</h2>
            <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left dark:bg-slate-800">
                  <tr>
                    <th className="px-2 py-2">#</th>
                    <th className="px-2 py-2">Combinación</th>
                    <th className="px-2 py-2">Veredicto</th>
                    <th className="px-2 py-2 text-right">Score</th>
                    <th className="px-2 py-2 text-right">OOS</th>
                    <th className="px-2 py-2 text-right">Mercado</th>
                    <th className="px-2 py-2 text-right">IC95%</th>
                    <th className="px-2 py-2 text-right">Ops</th>
                    <th className="px-2 py-2 text-right">Sharpe</th>
                    <th className="px-2 py-2 text-right">DD máx</th>
                    <th className="px-2 py-2 text-right">Supera mercado</th>
                  </tr>
                </thead>
                <tbody>
                  {candidatas.map((candidata) => (
                    <tr
                      key={candidata.rank}
                      className="border-t border-slate-100 dark:border-slate-800"
                    >
                      <td className="px-2 py-2 tabular-nums text-slate-400">{candidata.rank}</td>
                      <td className="px-2 py-2 whitespace-nowrap">
                        {etiquetaCandidata(candidata)}
                      </td>
                      <td className="px-2 py-2">
                        <VerdictBadge verdict={candidata.verdict} />
                        {candidata.rejections.length > 0 && (
                          <ul className="mt-1 list-inside list-disc text-xs text-slate-500 dark:text-slate-400">
                            {candidata.rejections.map((motivo) => (
                              <li key={motivo}>{motivo}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {toNumber(candidata.score)?.toFixed(1) ?? "—"}
                      </td>
                      <td
                        className={`px-2 py-2 text-right tabular-nums ${
                          (toNumber(candidata.oos_return_pct) ?? 0) < 0
                            ? "text-red-600 dark:text-red-400"
                            : "text-emerald-600 dark:text-emerald-400"
                        }`}
                      >
                        {formatPercent(candidata.oos_return_pct)}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums text-slate-500">
                        {formatPercent(candidata.market_return_pct)}
                      </td>
                      <td className="px-2 py-2 text-right whitespace-nowrap tabular-nums">
                        <FormatoIC low={candidata.ci95_low} high={candidata.ci95_high} />
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{candidata.trades}</td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {toNumber(candidata.sharpe_mean)?.toFixed(2) ?? "—"}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {formatPercent(candidata.max_drawdown_worst)}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {candidata.beats_market_windows}/{candidata.windows}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="font-medium">Ventanas ({report.windows.length})</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              La tabla que permite ver que el resultado no viene de una ventana suelta. La
              diferencia con el mercado se calcula al pintar: es una resta de dos columnas que ya
              están, y duplicarla sería una tercera fuente de verdad para el mismo número.
            </p>
            <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left dark:bg-slate-800">
                  <tr>
                    <th className="px-2 py-2">#</th>
                    <th className="px-2 py-2">In-sample</th>
                    <th className="px-2 py-2">Out-of-sample</th>
                    <th className="px-2 py-2">Elegida en el IS</th>
                    <th className="px-2 py-2 text-right">Ops OOS</th>
                    <th className="px-2 py-2 text-right">OOS</th>
                    <th className="px-2 py-2 text-right">Mercado</th>
                    <th className="px-2 py-2 text-right">Diferencia</th>
                    <th className="px-2 py-2 text-right">Sharpe</th>
                    <th className="px-2 py-2 text-right">DD</th>
                  </tr>
                </thead>
                <tbody>
                  {report.windows.map((ventana) => {
                    const diferencia =
                      (toNumber(ventana.oos_return_pct) ?? 0) -
                      (toNumber(ventana.market_return_pct) ?? 0);
                    return (
                      <tr
                        key={ventana.index}
                        className="border-t border-slate-100 dark:border-slate-800"
                      >
                        <td className="px-2 py-2 tabular-nums text-slate-400">{ventana.index}</td>
                        <td className="px-2 py-2 whitespace-nowrap text-slate-500">
                          {formatDateEs(ventana.is_from)} → {formatDateEs(ventana.is_to)}
                        </td>
                        <td className="px-2 py-2 whitespace-nowrap text-slate-500">
                          {formatDateEs(ventana.oos_from)} → {formatDateEs(ventana.oos_to)}
                        </td>
                        <td className="px-2 py-2 whitespace-nowrap">
                          {etiquetaEstrategia(ventana.selected_strategy)}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{ventana.oos_trades}</td>
                        <td className="px-2 py-2 text-right tabular-nums">
                          {formatPercent(ventana.oos_return_pct)}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-slate-500">
                          {formatPercent(ventana.market_return_pct)}
                        </td>
                        <td
                          className={`px-2 py-2 text-right tabular-nums ${
                            diferencia < 0
                              ? "text-red-600 dark:text-red-400"
                              : "text-emerald-600 dark:text-emerald-400"
                          }`}
                        >
                          {formatPercent(String(diferencia))}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">
                          {toNumber(ventana.oos_sharpe)?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">
                          {formatPercent(ventana.oos_max_drawdown_pct)}
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

      <section className="space-y-2">
        <h2 className="font-medium">Progreso</h2>
        <WalkForwardLogViewer logs={logs} connected={connected} />
      </section>
    </div>
  );
}
