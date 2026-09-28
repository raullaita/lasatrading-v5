import { useState } from "react";
import { ChevronDown, FlaskConical, Loader2, RefreshCw, TrendingUp } from "lucide-react";

import { ExcursionChart } from "../../components/Backtesting/ExcursionChart";
import { SweepTable } from "../../components/Backtesting/SweepTable";
import type {
  BacktestAnalysis,
  BacktestBenchmark,
  PatternCalibration,
  SweepGrid,
  SweepPoint,
} from "../../types/backtesting";
import { formatPercent, toNumber } from "../../utils/format";

/**
 * Seccion colapsable de analisis y calibracion.
 *
 * Va colapsada de entrada y se pide solo al abrirla, por dos razones. La
 * primera es que es lo mas caro de la pagina: el analisis lee todas las
 * operaciones del run y calcula percentiles, y quien solo ha venido a ver el
 * resultado no deberia pagar eso. La segunda es que tiene sentido cuando ya se
 * ha ledio el resultado y no antes: calibrar un run que no has mirado es
 * optimizar a ciegas.
 *
 * El barrido **no** se dispara solo, ni al abrir. Re-simula hasta 120
 * combinaciones y en el fixture real tarda 4,3 s; hacerlo sin que el usuario lo
 * pulse convertiria abrir un detalle en dejar el portatil caliente. Se lanza
 * con la rejilla que se ve en pantalla, que se puede cambiar antes de darle.
 *
 * Dos rejillas por defecto, la del run y la de los percentiles: la primera
 * responde "y si solo cambio esto", la segunda "y si pruebo lo que dicen los
 * datos". Ninguna es magica; las dos son la misma llamada con numeros distintos.
 */

/** Rejilla que envuelve la combinacion actual del run. */
function rejillaDelRun(analysis: BacktestAnalysis): SweepGrid {
  const tp = toNumber(analysis.strategy.strategy.take_profit_pct);
  const sl = toNumber(analysis.strategy.strategy.stop_loss_pct);
  // El nivel actual va siempre en la lista, mas la mitad, la mitad por encima y
  // un valor redondo de referencia. El `indexOf` quita duplicados: con un TP al
  // 0,5% la mitad es 0,25 y el redondo tambien 0,5, y repetir el nivel actual
  // dos veces haria que el backend simulase dos veces lo mismo.
  const conNiveles = (base: number | null, redondo: number): (number | null)[] =>
    [
      base === null ? null : Math.max(base * 0.5, 0.1),
      base,
      base === null ? null : base * 1.5,
      redondo,
    ].filter((valor, indice, todos) => todos.indexOf(valor) === indice) as (number | null)[];
  return {
    take_profit_pcts: conNiveles(tp, 0.5),
    stop_loss_pcts: conNiveles(sl, 2),
    max_holds: [12, 24],
  };
}

/** Rejilla construida alrededor de los percentiles que propone el analisis. */
function rejillaDePercentiles(analysis: BacktestAnalysis): SweepGrid {
  const tp = toNumber(analysis.suggested_take_profit_pct) ?? 1.0;
  const sl = toNumber(analysis.strategy.strategy.stop_loss_pct) ?? 1.0;
  return {
    take_profit_pcts: [null, tp * 0.75, tp, 2, 3],
    stop_loss_pcts: [sl * 0.75, sl, 2, 3],
    max_holds: [24],
  };
}

export function CalibrationSection({
  analysis,
  onSweep,
  onApply,
  sweep,
  benchmark,
  sweeping,
  sweepError,
}: {
  analysis: BacktestAnalysis;
  onSweep: (grid: SweepGrid) => void;
  /** Lanza un run nuevo con la combinacion elegida. */
  onApply: (point: SweepPoint) => void;
  sweep: SweepPoint[];
  /** Mercado de referencia del barrido; cambia con el, no con la rejilla. */
  benchmark: BacktestBenchmark | null;
  sweeping: boolean;
  sweepError: string | null;
}) {
  const [abierto, setAbierto] = useState(false);
  const [rejilla, setRejilla] = useState<"run" | "percentiles">("run");
  const [grupoAbierto, setGrupoAbierto] = useState<string | null>(null);

  const grid = rejilla === "run" ? rejillaDelRun(analysis) : rejillaDePercentiles(analysis);
  const combinaciones =
    grid.take_profit_pcts.length * grid.stop_loss_pcts.length * grid.max_holds.length;

  const clave = (grupo: PatternCalibration) => `${grupo.pattern_name}-${grupo.direction}`;

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <button
        type="button"
        onClick={() => setAbierto((prev) => !prev)}
        className="flex w-full items-center justify-between gap-3 p-5 text-left"
      >
        <span className="flex items-center gap-2">
          <FlaskConical className="h-5 w-5 text-indigo-500" />
          <span className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Análisis y calibración
          </span>
        </span>
        <span className="flex items-center gap-3">
          <span className="text-xs text-slate-400 dark:text-slate-500">
            {analysis.free_trades} de {analysis.trades} operaciones sin recortes
          </span>
          <ChevronDown
            className={`h-5 w-5 text-slate-400 transition-transform ${abierto ? "rotate-180" : ""}`}
          />
        </span>
      </button>

      {abierto && (
        <div className="space-y-6 border-t border-slate-200 p-5 dark:border-slate-800">
          <ul className="space-y-1.5 text-sm text-slate-600 dark:text-slate-300">
            {analysis.findings.map((texto) => (
              <li key={texto} className="flex gap-2">
                <span className="text-indigo-500">·</span>
                <span>{texto}</span>
              </li>
            ))}
          </ul>

          {analysis.warnings.length > 0 && (
            <ul className="space-y-1.5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
              {analysis.warnings.map((texto) => (
                <li key={texto} className="flex gap-2">
                  <span>!</span>
                  <span>{texto}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                Recorrido a favor · MFE
              </h4>
              <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
                {analysis.pooled_mfe.count} operaciones que ningún nivel cortó
              </p>
              <ExcursionChart stats={analysis.pooled_mfe} />
            </div>
            <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                Recorrido en contra · MAE
              </h4>
              <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
                {analysis.pooled_mae.count} operaciones que ningún nivel cortó
              </p>
              <ExcursionChart stats={analysis.pooled_mae} color="rose" />
            </div>
          </div>

          <div>
            <h4 className="mb-2 text-sm font-bold text-slate-900 dark:text-slate-100">
              Por patrón y dirección
            </h4>
            <div className="space-y-2">
              {analysis.groups.map((grupo) => {
                const id = clave(grupo);
                const abierto = grupoAbierto === id;
                return (
                  <div
                    key={id}
                    className="rounded-xl border border-slate-200 dark:border-slate-800"
                  >
                    <button
                      type="button"
                      onClick={() => setGrupoAbierto(abierto ? null : id)}
                      className="flex w-full items-center justify-between gap-3 p-3 text-left text-sm"
                    >
                      <span className="font-medium text-slate-800 dark:text-slate-100">
                        {grupo.pattern_name}
                        <span className="ml-2 text-xs text-slate-400">
                          {grupo.direction === "long" ? "largo" : "corto"} · {grupo.trades} ops ·{" "}
                          {grupo.free_trades} libres
                        </span>
                      </span>
                      <span className="flex items-center gap-3 text-xs">
                        {grupo.suggested_take_profit_pct !== null && (
                          <span className="text-emerald-600 dark:text-emerald-400">
                            TP {formatPercent(grupo.suggested_take_profit_pct)}
                          </span>
                        )}
                        <ChevronDown
                          className={`h-4 w-4 text-slate-400 transition-transform ${
                            abierto ? "rotate-180" : ""
                          }`}
                        />
                      </span>
                    </button>
                    {abierto && (
                      <div className="space-y-3 border-t border-slate-200 p-3 dark:border-slate-800">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div>
                            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                              Ganadoras: MFE
                            </p>
                            <ExcursionChart stats={grupo.winner_mfe} />
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                              Perdedoras: MAE
                            </p>
                            <ExcursionChart stats={grupo.loser_mae} color="rose" />
                          </div>
                        </div>
                        {grupo.findings.map((texto) => (
                          <p key={texto} className="text-xs text-slate-600 dark:text-slate-300">
                            · {texto}
                          </p>
                        ))}
                        {grupo.warnings.map((texto) => (
                          <p key={texto} className="text-xs text-amber-700 dark:text-amber-400">
                            ! {texto}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <h4 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-slate-100">
              <TrendingUp className="h-4 w-4 text-indigo-500" />
              Barrido de parámetros
            </h4>
            <p className="mb-3 mt-1 text-xs text-slate-500 dark:text-slate-400">
              Vuelve a simular este mismo run con otras combinaciones de take profit, stop loss y
              velas máximas. No guarda nada: es una pregunta, no un experimento.
            </p>

            <div className="mb-3 flex flex-wrap items-center gap-3">
              {(["run", "percentiles"] as const).map((opcion) => (
                <label key={opcion} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="rejilla"
                    checked={rejilla === opcion}
                    onChange={() => setRejilla(opcion)}
                    className="h-4 w-4 border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-slate-700 dark:text-slate-300">
                    {opcion === "run"
                      ? "Alrededor de los parámetros del run"
                      : "Alrededor de los percentiles propuestos"}
                  </span>
                </label>
              ))}
              <span className="text-xs text-slate-400">{combinaciones} combinaciones</span>
              <button
                type="button"
                onClick={() => onSweep(grid)}
                disabled={sweeping}
                className="ml-auto inline-flex items-center gap-2 rounded-lg border border-indigo-300 px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-900 dark:text-indigo-400 dark:hover:bg-indigo-950/40"
              >
                {sweeping ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {sweeping ? "Simulando…" : "Simular"}
              </button>
            </div>

            {sweepError && (
              <p className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
                {sweepError}
              </p>
            )}

            {sweep.length > 0 && (
              <>
                <SweepTable points={sweep} benchmark={benchmark} onApply={onApply} />
                <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
                  Ordenado de mejor a peor por PnL neto. La fila «actual» es la combinación con la
                  que se hizo este run: sin ella, «la mejor» no significa nada.
                </p>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
