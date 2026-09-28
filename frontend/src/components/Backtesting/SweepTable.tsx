import type { SweepPoint } from "../../types/backtesting";
import {
  formatMoney,
  formatPctPlain,
  formatPercent,
  formatRate,
  toNumber,
} from "../../utils/format";

/**
 * Tabla comparativa del barrido de TP, SL y `max_hold`.
 *
 * La tabla llega **ya ordenada por el backend** de mejor a peor por PnL, y no se
 * reordena aqui: el orden por defecto es por resultado, que es la pregunta que
 * se hace el usuario, y las columnas ordenables lo hacen de forma explicita
 * cuando lo que interesa es otra cosa.
 *
 * La fila marcada con `is_baseline` es la combinacion que ya usaba el run, y se
 * resalta en vez de esconderla. Es lo que convierte la tabla en una comparacion
 * y no en un ranking: sin ver donde cae lo que tienes, "la mejor" no significa
 * nada. Si los parametros del run no estaban en la rejilla no hay ninguna fila
 * marcada, porque marcar la mejor seria mentir sobre cual es el punto de
 * partida.
 */

const EXIT_LABELS: Record<string, string> = {
  take_profit: "TP",
  stop_loss: "SL",
  timeout: "Tiempo",
  end_of_data: "Fin",
};

function nivel(value: string | null): string {
  return value === null ? "sin" : `${toNumber(value)?.toFixed(2) ?? "—"}%`;
}

export function SweepTable({
  points,
  onApply,
}: {
  points: SweepPoint[];
  /** Lanza un nuevo run con esta combinacion. */
  onApply?: (point: SweepPoint) => void;
}) {
  if (points.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-slate-400 dark:text-slate-500">
        Ninguna combinación de la rejilla produce una estrategia válida
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            <th className="px-4 py-2.5">TP</th>
            <th className="px-4 py-2.5">SL</th>
            <th className="px-4 py-2.5 text-right">Velas</th>
            <th className="px-4 py-2.5 text-right">Ops</th>
            <th className="px-4 py-2.5 text-right">Win rate</th>
            <th className="px-4 py-2.5 text-right">PnL neto</th>
            <th className="px-4 py-2.5 text-right">Retorno</th>
            <th className="px-4 py-2.5 text-right">DD máx.</th>
            <th className="px-4 py-2.5 text-right">Sharpe</th>
            <th className="px-4 py-2.5">Salidas</th>
            {onApply && <th className="px-4 py-2.5" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {points.map((point) => {
            const pnl = toNumber(point.net_pnl);
            const clave = `${point.take_profit_pct}-${point.stop_loss_pct}-${point.max_hold}`;
            return (
              <tr
                key={clave}
                className={
                  point.is_baseline
                    ? "bg-amber-50 dark:bg-amber-950/20"
                    : "hover:bg-slate-50 dark:hover:bg-slate-800/50"
                }
              >
                <td className="px-4 py-2 font-medium">
                  {nivel(point.take_profit_pct)}
                  {point.is_baseline && (
                    <span className="ml-1.5 text-[10px] font-normal uppercase text-amber-700 dark:text-amber-400">
                      actual
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 font-medium">{nivel(point.stop_loss_pct)}</td>
                <td className="px-4 py-2 text-right">{point.max_hold}</td>
                <td className="px-4 py-2 text-right">
                  {point.total_trades.toLocaleString("es-ES")}
                </td>
                <td className="px-4 py-2 text-right">{formatRate(point.win_rate)}</td>
                <td
                  className={
                    pnl === null
                      ? "px-4 py-2 text-right"
                      : `px-4 py-2 text-right font-medium ${
                          pnl >= 0
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-rose-600 dark:text-rose-400"
                        }`
                  }
                >
                  {pnl !== null && pnl >= 0 ? "+" : ""}
                  {formatMoney(point.net_pnl)}
                </td>
                <td className="px-4 py-2 text-right">{formatPercent(point.total_return_pct)}</td>
                <td className="px-4 py-2 text-right">{formatPercent(point.max_drawdown_pct)}</td>
                <td className="px-4 py-2 text-right">{formatPctPlain(point.sharpe_ratio)}</td>
                <td className="px-4 py-2 text-xs text-slate-500 dark:text-slate-400">
                  {Object.entries(point.exits)
                    .map(([motivo, cuenta]) => `${EXIT_LABELS[motivo] ?? motivo} ${cuenta}`)
                    .join(" · ")}
                </td>
                {onApply && (
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => onApply(point)}
                      className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                    >
                      Probar
                    </button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
