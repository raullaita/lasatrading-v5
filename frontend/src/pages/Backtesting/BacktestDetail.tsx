import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Ban, Loader2, Send, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { BacktestLogViewer } from "../../components/Backtesting/BacktestLogViewer";
import { EquityChart } from "../../components/Backtesting/EquityChart";
import { SortableTh } from "../../components/ui/SortableTh";
import { StatusBadge } from "../../components/ui/StatusBadge";
import {
  cancelBacktest,
  deleteBacktest,
  getBacktest,
  getBacktestEquity,
  getBacktestSummary,
  getBacktestTrades,
  requeueBacktest,
} from "../../services/backtestsApi";
import { getPatternScan } from "../../services/patternsApi";
import { connectBacktestLogs, disconnectBacktestLogs } from "../../services/backtestsWebSocket";
import {
  BACKTEST_TERMINAL_STATUSES,
  EXIT_REASON_LABELS,
  type BacktestEquitySeries,
  type BacktestLog,
  type BacktestRunResponse,
  type BacktestSummary,
  type BacktestTrade,
  type ExitReason,
  type TradeDirection,
} from "../../types/backtesting";
import {
  formatDateTimeEs,
  formatMoney,
  formatPercent,
  formatRate,
  toNumber,
} from "../../utils/format";

/** Tope del backend en `/backtests/{id}/trades` (`page_size` le=200). */
const TRADE_PAGE_SIZE = 100;

/** Columnas que admite `SORTABLE_TRADE_COLUMNS` del backend. */
const TRADE_SORTABLE = new Set([
  "entry_timestamp",
  "exit_timestamp",
  "net_pnl",
  "return_pct",
  "bars_held",
  "mae",
  "mfe",
]);

const DIRECTION_LABELS: Record<TradeDirection, string> = {
  long: "Largo",
  short: "Corto",
};

export default function BacktestDetail() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();

  const [run, setRun] = useState<BacktestRunResponse | null>(null);
  const [scanLabel, setScanLabel] = useState("");
  const [logs, setLogs] = useState<BacktestLog[]>([]);
  const [summary, setSummary] = useState<BacktestSummary | null>(null);
  const [equity, setEquity] = useState<BacktestEquitySeries | null>(null);
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [tradeTotal, setTradeTotal] = useState(0);
  const [tradeNetPnl, setTradeNetPnl] = useState<string | null>(null);
  const [tradePage, setTradePage] = useState(1);
  const [tradePattern, setTradePattern] = useState("");
  const [tradeDirection, setTradeDirection] = useState("");
  const [tradeExitReason, setTradeExitReason] = useState("");
  const [tradeSortBy, setTradeSortBy] = useState("entry_timestamp");
  const [tradeSortOrder, setTradeSortOrder] = useState<"asc" | "desc">("desc");
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [wsError, setWsError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [requeuing, setRequeuing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const disposedRef = useRef(false);
  /** Resultado (summary + equity) ya cargado para este intento del run. */
  const resultLoadedRef = useRef(false);
  /**
   * Contador de intentos, igual que en `ScanDetail`: al reenviar un run, el
   * sondeo y el WebSocket se paran solos al terminar, y este contador es lo que
   * los rearma sin tocar nada mas.
   */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    disposedRef.current = false;
    resultLoadedRef.current = false;
    return () => {
      disposedRef.current = true;
      disconnectBacktestLogs(runId);
    };
  }, [runId]);

  useEffect(() => {
    const disconnect = connectBacktestLogs(runId, {
      onLog: (log) => setLogs((prev) => [...prev, log]),
      onConnectionChange: setWsConnected,
      onError: (message) => setWsError(message),
    });
    setWsError(null);
    return disconnect;
  }, [runId, attempt]);

  /** Símbolo y timeframe vienen del escaneo origen, no del run. */
  useEffect(() => {
    // `setScanLabel` no se resetea: si el escaneo origen desapareciera, mejor
    // conservar la ultima etiqueta valida que pintar «—».
    if (!run) return;
    void getPatternScan(run.scan_job_id)
      .then((scan) => {
        if (!disposedRef.current) setScanLabel(`${scan.symbol} · ${scan.timeframe}`);
      })
      .catch(() => undefined);
  }, [run]);

  useEffect(() => {
    const present = (next: BacktestRunResponse) => {
      if (disposedRef.current) return;
      setRun(next);
      setLoading(false);
      setLoadError(null);
    };

    void getBacktest(runId)
      .then(present)
      .catch(() => {
        if (!disposedRef.current) {
          setLoadError("Backtest no encontrado.");
          setLoading(false);
        }
      });

    const timer = window.setInterval(() => {
      void getBacktest(runId)
        .then((next) => {
          present(next);
          if (BACKTEST_TERMINAL_STATUSES.includes(next.status)) {
            window.clearInterval(timer);
            disconnectBacktestLogs(runId);
          }
        })
        .catch(() => undefined);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [runId, attempt]);

  /**
   * Summary y equity se cargan una vez, cuando el run esta en estado terminal.
   * Entre medias no cambian, y recargarlos en cada sondeo seria pedir media
   * tabla la mitad del tiempo.
   */
  useEffect(() => {
    if (!run) return;
    if (!BACKTEST_TERMINAL_STATUSES.includes(run.status)) return;
    if (resultLoadedRef.current) return;
    resultLoadedRef.current = true;
    void getBacktestSummary(runId)
      .then((next) => {
        if (!disposedRef.current) setSummary(next);
      })
      .catch(() => undefined);
    void getBacktestEquity(runId, 500)
      .then((next) => {
        if (!disposedRef.current) setEquity(next);
      })
      .catch(() => undefined);
  }, [run, runId]);

  const loadTrades = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await getBacktestTrades(runId, {
        pattern: tradePattern ? [tradePattern] : undefined,
        direction: tradeDirection ? [tradeDirection as TradeDirection] : undefined,
        exit_reason: tradeExitReason ? [tradeExitReason as ExitReason] : undefined,
        sort_by: tradeSortBy,
        sort_order: tradeSortOrder,
        page: tradePage,
        page_size: TRADE_PAGE_SIZE,
      });
      if (!disposedRef.current) {
        setTrades(data.trades);
        setTradeTotal(data.total);
        setTradeNetPnl(data.total_net_pnl);
      }
    } catch {
      // La tabla de operaciones es secundaria: que falle no tumba el resto.
    }
  }, [
    runId,
    tradePattern,
    tradeDirection,
    tradeExitReason,
    tradeSortBy,
    tradeSortOrder,
    tradePage,
  ]);

  useEffect(() => {
    if (!run) return;
    if (run.total_trades === 0) return;
    void loadTrades();
  }, [run, loadTrades]);

  const handleTradeSort = (key: string) => {
    if (!TRADE_SORTABLE.has(key)) return;
    if (tradeSortBy === key) {
      setTradeSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setTradeSortBy(key);
      setTradeSortOrder("asc");
    }
    setTradePage(1);
  };

  async function onCancel() {
    if (!window.confirm("¿Cancelar este backtest? El trabajo se detendrá en el siguiente tramo.")) {
      return;
    }
    setCancelling(true);
    setActionError(null);
    try {
      setRun(await cancelBacktest(runId));
    } catch {
      setActionError("No se pudo cancelar el backtest.");
    } finally {
      setCancelling(false);
    }
  }

  async function onRequeue() {
    if (!window.confirm("¿Reenviar este backtest a la cola de Celery?")) return;
    setRequeuing(true);
    setActionError(null);
    try {
      setRun(await requeueBacktest(runId));
      // El resultado del intento anterior ya no vale y el sondeo/socket estan
      // parados desde el estado final: subir `attempt` los rearma y se limpia
      // el resumen y los logs para que no se dupliquen al reintroyectar el
      // historico entero.
      resultLoadedRef.current = false;
      setSummary(null);
      setEquity(null);
      setLogs([]);
      setAttempt((n) => n + 1);
    } catch {
      setActionError("No se pudo reenviar el backtest.");
    } finally {
      setRequeuing(false);
    }
  }

  async function onDelete() {
    if (!window.confirm("¿Borrar este backtest, sus operaciones y su curva de equity?")) return;
    setDeleting(true);
    setActionError(null);
    try {
      await deleteBacktest(runId);
      navigate("/backtesting");
    } catch {
      setActionError("No se pudo borrar el backtest.");
      setDeleting(false);
    }
  }

  const patternOptions = useMemo(() => {
    const names = new Set<string>();
    if (summary) for (const b of summary.by_pattern) names.add(b.pattern_name);
    return [...names].sort();
  }, [summary]);

  if (loading) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
      </main>
    );
  }

  if (loadError || !run) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8 dark:bg-slate-950">
        <div className="text-center">
          <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {loadError ?? "Sin datos"}
          </p>
          <Link
            to="/backtesting"
            className="mt-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Volver a backtests
          </Link>
        </div>
      </main>
    );
  }

  const live = !BACKTEST_TERMINAL_STATUSES.includes(run.status);
  const needsRequeue = run.status === "pending" || run.status === "failed";
  const strategy = run.strategy;
  const pnl = toNumber(run.net_pnl);
  const ret = toNumber(run.total_return_pct);
  const tradePages = Math.max(1, Math.ceil(tradeTotal / TRADE_PAGE_SIZE));
  const finished = !live;

  const strategyLine = [
    strategy.take_profit_pct !== null ? `TP ${strategy.take_profit_pct}%` : "sin TP",
    strategy.stop_loss_pct !== null ? `SL ${strategy.stop_loss_pct}%` : "sin SL",
    `máx ${strategy.max_hold} velas`,
    strategy.allow_short ? "cortos" : "solo largos",
  ].join(" · ");

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-6xl">
        <Link
          to="/backtesting"
          className="text-sm text-indigo-600 hover:underline dark:text-indigo-400"
        >
          ← Backtests
        </Link>

        <div className="mb-6 mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <StatusBadge status={run.status} />
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {scanLabel || "Backtest"} · {formatDateTimeEs(run.created_at)}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {live && (
              <button
                type="button"
                onClick={() => void onCancel()}
                disabled={cancelling}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:hover:bg-rose-950/50"
              >
                <Ban className="h-4 w-4" />
                {cancelling ? "Cancelando…" : "Cancelar"}
              </button>
            )}
            {needsRequeue && (
              <button
                type="button"
                onClick={() => void onRequeue()}
                disabled={requeuing}
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 dark:border-emerald-900 dark:bg-slate-900 dark:hover:bg-emerald-950/50"
              >
                <Send className={`h-4 w-4 ${requeuing ? "animate-pulse" : ""}`} />
                {requeuing ? "Reenviando…" : "Reenviar"}
              </button>
            )}
            <button
              type="button"
              onClick={() => void onDelete()}
              disabled={deleting}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:hover:bg-rose-950/50"
            >
              <Trash2 className="h-4 w-4" />
              {deleting ? "Borrando…" : "Borrar backtest"}
            </button>
          </div>
        </div>

        {actionError && (
          <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            {actionError}
          </p>
        )}

        {wsError && (
          <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
            Logs en directo no disponibles: {wsError}. El estado y el resultado del run se siguen
            actualizando; los logs se reconectan solos.
          </p>
        )}

        {run.error_message && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 dark:border-rose-900 dark:bg-rose-950/40">
            <p className="text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
              Error del backtest
            </p>
            <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-rose-700 dark:text-rose-300">
              {run.error_message}
            </p>
            {run.status === "failed" && (
              <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                Si el escaneo origen no estaba completo, termina el escaneo en «Patrones» y usa
                «Reenviar».
              </p>
            )}
          </div>
        )}

        <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Meta label="Estrategia" value={strategyLine} />
          <Meta
            label="Señales"
            value={summary ? summary.total_signals.toLocaleString("es-ES") : "—"}
          />
          <Meta label="Operaciones" value={run.total_trades.toLocaleString("es-ES")} />
          <Meta label="Señales saltadas" value={run.skipped_signals.toLocaleString("es-ES")} />
        </div>

        <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Metric label="Capital inicial" value={formatMoney(run.initial_capital)} />
          <Metric label="Capital final" value={formatMoney(run.equity_final)} />
          <Metric
            label="PnL neto"
            value={pnl === null ? "—" : `${pnl >= 0 ? "+" : ""}${formatMoney(run.net_pnl)}`}
            tone={pnl === null ? "neutral" : pnl >= 0 ? "positive" : "negative"}
          />
          <Metric
            label="Retorno"
            value={ret === null ? "—" : formatPercent(run.total_return_pct)}
            tone={ret === null ? "neutral" : ret >= 0 ? "positive" : "negative"}
          />
          <Metric
            label="Win rate"
            value={`${formatRate(run.win_rate)} · ${run.total_trades} op.`}
          />
          <Metric
            label="Profit factor"
            value={run.profit_factor ? formatPctPlain(run.profit_factor) : "—"}
          />
          <Metric label="Drawdown máx." value={formatPercent(run.max_drawdown_pct)} />
          <Metric
            label="Sharpe"
            value={run.sharpe_ratio ? formatPctPlain(run.sharpe_ratio) : "—"}
          />
        </div>

        <div className="mb-6">
          <BacktestLogViewer logs={logs} />
          {!wsConnected && logs.length > 0 && finished && (
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
              Run terminado: los logs son el historico final.
            </p>
          )}
        </div>

        {finished && summary && (
          <>
            <div className="mb-6 space-y-4">
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Resumen</h2>
              <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
                    <tr>
                      <th className="px-4 py-2.5">Patrón</th>
                      <th className="px-4 py-2.5">Dirección</th>
                      <th className="px-4 py-2.5 text-right">Operaciones</th>
                      <th className="px-4 py-2.5 text-right">Aciertos</th>
                      <th className="px-4 py-2.5 text-right">Win rate</th>
                      <th className="px-4 py-2.5 text-right">Retorno medio</th>
                      <th className="px-4 py-2.5 text-right">PnL neto</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {summary.by_pattern.length === 0 && (
                      <tr>
                        <td
                          colSpan={7}
                          className="px-4 py-8 text-center text-slate-500 dark:text-slate-400"
                        >
                          Sin operaciones para este backtest.
                        </td>
                      </tr>
                    )}
                    {summary.by_pattern.map((b) => {
                      const bn = toNumber(b.net_pnl);
                      const wr = toNumber(b.win_rate);
                      return (
                        <tr
                          key={`${b.pattern_name}-${b.direction}`}
                          className="hover:bg-slate-50 dark:hover:bg-slate-800/50"
                        >
                          <td className="px-4 py-2.5 font-medium text-slate-800 dark:text-slate-200">
                            {b.pattern_name}
                          </td>
                          <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                            {DIRECTION_LABELS[b.direction]}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                            {b.trades.toLocaleString("es-ES")}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                            {b.wins} / {b.trades}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                            {wr === null ? "—" : formatRate(b.win_rate)}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                            {b.avg_return_pct ? formatPercent(b.avg_return_pct) : "—"}
                          </td>
                          <td
                            className={`px-4 py-2.5 text-right font-medium ${
                              bn === null
                                ? "text-slate-400 dark:text-slate-500"
                                : bn >= 0
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : "text-rose-600 dark:text-rose-400"
                            }`}
                          >
                            {bn === null ? "—" : `${bn >= 0 ? "+" : ""}${formatMoney(b.net_pnl)}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div>
                <h3 className="mb-2 text-sm font-bold text-slate-900 dark:text-slate-100">
                  Motivos de cierre
                </h3>
                <div className="flex flex-wrap gap-3">
                  {summary.by_exit_reason.map((r) => {
                    const rn = toNumber(r.net_pnl);
                    const tone =
                      r.exit_reason === "take_profit"
                        ? "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40"
                        : r.exit_reason === "stop_loss"
                          ? "border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40"
                          : "border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900";
                    return (
                      <div key={r.exit_reason} className={`rounded-xl border px-4 py-3 ${tone}`}>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {EXIT_REASON_LABELS[r.exit_reason]}
                        </p>
                        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                          {r.trades.toLocaleString("es-ES")}
                          <span className="ml-1 font-normal text-slate-400 dark:text-slate-500">
                            op. ·{" "}
                            {rn === null ? "—" : `${rn >= 0 ? "+" : ""}${formatMoney(r.net_pnl)}`}
                          </span>
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="mb-6">{equity ? <EquityChart points={equity.points} /> : null}</div>
          </>
        )}

        {finished && !summary && run.total_trades === 0 && (
          <p className="mb-6 rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Este backtest no abrió ninguna operación entre sus señales.
          </p>
        )}

        {run.total_trades > 0 && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Operaciones</h2>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {tradeTotal.toLocaleString("es-ES")} operaciones · PnL filtrado:{" "}
                {tradeNetPnl === null ? "—" : formatMoney(tradeNetPnl)}
              </span>
            </div>

            <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  Patrón
                </span>
                <select
                  value={tradePattern}
                  onChange={(e) => {
                    setTradePattern(e.target.value);
                    setTradePage(1);
                  }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                >
                  <option value="">Todos</option>
                  {patternOptions.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  Dirección
                </span>
                <select
                  value={tradeDirection}
                  onChange={(e) => {
                    setTradeDirection(e.target.value);
                    setTradePage(1);
                  }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                >
                  <option value="">Todas</option>
                  <option value="long">Largo</option>
                  <option value="short">Corto</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  Motivo de cierre
                </span>
                <select
                  value={tradeExitReason}
                  onChange={(e) => {
                    setTradeExitReason(e.target.value);
                    setTradePage(1);
                  }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                >
                  <option value="">Todos</option>
                  {(Object.keys(EXIT_REASON_LABELS) as ExitReason[]).map((r) => (
                    <option key={r} value={r}>
                      {EXIT_REASON_LABELS[r]}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
                  <tr>
                    <SortableTh
                      label="Entrada"
                      sortKey="entry_timestamp"
                      sortBy={tradeSortBy}
                      sortOrder={tradeSortOrder}
                      onSort={handleTradeSort}
                    />
                    <th className="px-4 py-2.5">Patrón</th>
                    <th className="px-4 py-2.5">Dir.</th>
                    <th className="px-4 py-2.5 text-right">P. entrada</th>
                    <th className="px-4 py-2.5 text-right">P. salida</th>
                    <SortableTh
                      label="Retorno"
                      sortKey="return_pct"
                      sortBy={tradeSortBy}
                      sortOrder={tradeSortOrder}
                      onSort={handleTradeSort}
                      className="text-right"
                    />
                    <SortableTh
                      label="PnL neto"
                      sortKey="net_pnl"
                      sortBy={tradeSortBy}
                      sortOrder={tradeSortOrder}
                      onSort={handleTradeSort}
                      className="text-right"
                    />
                    <SortableTh
                      label="Velas"
                      sortKey="bars_held"
                      sortBy={tradeSortBy}
                      sortOrder={tradeSortOrder}
                      onSort={handleTradeSort}
                      className="text-right"
                    />
                    <th className="px-4 py-2.5">Motivo</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {trades.length === 0 && (
                    <tr>
                      <td
                        colSpan={9}
                        className="px-4 py-8 text-center text-slate-500 dark:text-slate-400"
                      >
                        Sin operaciones con estos filtros.
                      </td>
                    </tr>
                  )}
                  {trades.map((t) => {
                    const tn = toNumber(t.net_pnl);
                    const tr = toNumber(t.return_pct);
                    return (
                      <tr key={t.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                        <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                          {formatDateTimeEs(t.entry_timestamp)}
                        </td>
                        <td className="px-4 py-2.5 font-medium text-slate-800 dark:text-slate-200">
                          {t.pattern_name}
                        </td>
                        <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                          {DIRECTION_LABELS[t.direction]}
                        </td>
                        <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                          {formatPrice(t.entry_price)}
                        </td>
                        <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                          {t.exit_price ? formatPrice(t.exit_price) : "—"}
                        </td>
                        <td
                          className={`px-4 py-2.5 text-right ${
                            tr === null
                              ? "text-slate-400 dark:text-slate-500"
                              : tr >= 0
                                ? "text-emerald-600 dark:text-emerald-400"
                                : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {tr === null ? "—" : formatPercent(t.return_pct)}
                        </td>
                        <td
                          className={`px-4 py-2.5 text-right font-medium ${
                            tn === null
                              ? "text-slate-400 dark:text-slate-500"
                              : tn >= 0
                                ? "text-emerald-600 dark:text-emerald-400"
                                : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {tn === null ? "—" : `${tn >= 0 ? "+" : ""}${formatMoney(t.net_pnl)}`}
                        </td>
                        <td className="px-4 py-2.5 text-right text-slate-600 dark:text-slate-300">
                          {t.bars_held.toLocaleString("es-ES")}
                        </td>
                        <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">
                          {t.exit_reason ? EXIT_REASON_LABELS[t.exit_reason] : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {tradePages > 1 && (
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Página {tradePage} de {tradePages}
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={tradePage <= 1}
                    onClick={() => setTradePage((p) => p - 1)}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
                  >
                    Anterior
                  </button>
                  <button
                    type="button"
                    disabled={tradePage >= tradePages}
                    onClick={() => setTradePage((p) => p + 1)}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
                  >
                    Siguiente
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

/** Precio sin simbolo y con separador español, hasta 2 decimales. */
function formatPrice(value: string): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return n.toLocaleString("es-ES", { maximumFractionDigits: 2 });
}

/** Ratio numerico sin sufijo (profit factor, sharpe). */
function formatPctPlain(value: string): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return n.toLocaleString("es-ES", { maximumFractionDigits: 2 });
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative";
}) {
  const color =
    tone === "positive"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "negative"
        ? "text-rose-600 dark:text-rose-400"
        : "text-slate-800 dark:text-slate-200";
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-0.5 truncate text-sm font-semibold ${color}`}>{value}</p>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs capitalize text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-0.5 truncate text-sm font-medium text-slate-800 dark:text-slate-200">
        {value}
      </p>
    </div>
  );
}
