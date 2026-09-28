/**
 * Tipos del modulo de backtesting, espejo de `backend/app/modules/backtesting/schemas.py`.
 *
 * Convención heredada de `types/patterns.ts`: nombres en snake_case (lo que
 * serializa FastAPI) y fechas como strings ISO 8601 en UTC.
 *
 * Diferencia importante: **el dinero y los ratios llegan como string**. Las
 * columnas de `backtest_runs` son `Decimal` y pydantic serializa los `Decimal`
 * a string en JSON (`"net_pnl":"-75.44133916"`), mientras que los `int` de
 * siempre (``trades``, ``bars_held``) llegan como number y el JSONB `strategy`
 * como objetos nativos. No se convierten a number en la capa de tipos: la
 * conversion la hace el formateador en el punto de uso, que es quien decide
 * cuantos decimales enseñar.
 */

// ---------------------------------------------------------------------------
// Estados y enums
// ---------------------------------------------------------------------------

export type BacktestRunStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

/**
 * Estados en los que el WebSocket de logs cierra por sí mismo: el backend hace
 * `websocket.close()` cuando los ve. Mismo papel que `PATTERN_TERMINAL_STATUSES`.
 */
export const BACKTEST_TERMINAL_STATUSES: readonly BacktestRunStatus[] = [
  "completed",
  "failed",
  "cancelled",
];

/** `ExitReason`. `end_of_data` no es un fallo de la estrategia: es falta de velas. */
export type ExitReason = "take_profit" | "stop_loss" | "timeout" | "end_of_data";

/** Etiqueta para pintar un motivo de cierre. */
export const EXIT_REASON_LABELS: Record<ExitReason, string> = {
  take_profit: "Take profit",
  stop_loss: "Stop loss",
  timeout: "Tiempo límite",
  end_of_data: "Fin de datos",
};

/** Sentido de una operacion cerrada (no confundir con el filtro bullish/bearish). */
export type TradeDirection = "long" | "short";

// ---------------------------------------------------------------------------
// Estrategia
// ---------------------------------------------------------------------------

/** Filtro de direcciones en el POST: la señal es bullish/bearish. */
export type SignalDirection = "bullish" | "bearish";

/**
 * `BacktestStrategyIn`. Cuerpo de la estrategia del POST.
 *
 * `take_profit_pct` y `stop_loss_pct` admiten `null` (sin stop): el motor
 * simula con el objetivo que exista. El resto tienen defaults del backend.
 */
export interface BacktestStrategyIn {
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_hold: number;
  fee_bps: number;
  initial_capital: number;
  use_fraction: number;
  allow_short: boolean;
}

/** `BacktestCreateIn`. */
export interface BacktestCreateIn {
  scan_job_id: string;
  strategy: BacktestStrategyIn;
  /** `null` = todos los patrones del escaneo. */
  patterns?: string[] | null;
  directions?: SignalDirection[] | null;
}

/**
 * `BacktestRunOut.strategy`, el JSONB congelado del motor (`StrategyConfig`).
 * Forma de `engine.StrategyConfig`, no el `BacktestStrategyIn` (añade
 * `entry_offset` y conserva los filtros ya aplicados).
 */
export interface BacktestRunStrategy {
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_hold: number;
  fee_bps: number;
  initial_capital: number;
  use_fraction: number;
  allow_short: boolean;
  entry_offset: number;
  patterns?: string[] | null;
  directions?: SignalDirection[] | null;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/**
 * `BacktestRunListItem`. Fila de `GET /backtests`.
 *
 * No trae `scan_job_id` **ni** `strategy`: la lista quiere cabecera para una
 * tabla, y el símbolo hay que recuperarlo preguntando el escaneo por `id` en
 * el detalle. El `win_rate` llega como fraccion (0.42 = 42%).
 */
export interface BacktestRunListItem {
  id: string;
  status: BacktestRunStatus;
  initial_capital: string;
  equity_final: string | null;
  total_trades: number;
  net_pnl: string | null;
  total_return_pct: string | null;
  win_rate: string | null;
  max_drawdown_pct: string | null;
  created_at: string;
}

/** `BacktestRunListOut`. */
export interface BacktestRunListOut {
  runs: BacktestRunListItem[];
  total: number;
}

/**
 * `BacktestRunOut`. Run completo; respuesta de POST, GET /{id}, /cancel y
 * /requeue. El dinero y los ratios van en string (ver docstring del archivo).
 */
export interface BacktestRunResponse {
  id: string;
  scan_job_id: string;
  status: BacktestRunStatus;
  strategy: BacktestRunStrategy;
  initial_capital: string;
  equity_final: string | null;
  total_trades: number;
  skipped_signals: number;
  truncated_trades: number;
  net_pnl: string | null;
  total_return_pct: string | null;
  win_rate: string | null;
  profit_factor: string | null;
  max_drawdown_pct: string | null;
  sharpe_ratio: string | null;
  avg_bars_held: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// Trades
// ---------------------------------------------------------------------------

/** `BacktestTradeOut`. */
export interface BacktestTrade {
  id: string;
  signal_timestamp: string;
  pattern_name: string;
  direction: TradeDirection;
  entry_timestamp: string;
  entry_price: string;
  exit_timestamp: string | null;
  exit_price: string | null;
  exit_reason: ExitReason | null;
  quantity: string;
  gross_pnl: string | null;
  fees: string;
  net_pnl: string | null;
  return_pct: string | null;
  bars_held: number;
  equity_after: string | null;
  mae: string | null;
  mfe: string | null;
}

/** `BacktestTradeListOut`. `total_net_pnl` es el PnL de TODOS los que casan. */
export interface BacktestTradeListOut {
  trades: BacktestTrade[];
  total: number;
  total_net_pnl: string | null;
}

// ---------------------------------------------------------------------------
// Equity
// ---------------------------------------------------------------------------

/** `BacktestEquityPointOut`. */
export interface BacktestEquityPoint {
  timestamp: string;
  equity: string;
  drawdown_pct: string;
}

/** `BacktestEquitySeriesOut`. `total_points` vs `returned` = muestreo real. */
export interface BacktestEquitySeries {
  points: BacktestEquityPoint[];
  total_points: number;
  returned: number;
  max_drawdown_pct: string | null;
}

// ---------------------------------------------------------------------------
// Resumen
// ---------------------------------------------------------------------------

/** `BacktestPatternBreakdownOut`. */
export interface BacktestPatternBreakdown {
  pattern_name: string;
  direction: TradeDirection;
  trades: number;
  wins: number;
  losses: number;
  net_pnl: string;
  avg_return_pct: string | null;
  win_rate: string | null;
  avg_bars_held: string | null;
  avg_mae: string | null;
  avg_mfe: string | null;
}

/** `BacktestExitReasonOut`. */
export interface BacktestExitReasonBreakdown {
  exit_reason: ExitReason;
  trades: number;
  net_pnl: string;
}

/** `BacktestSummaryOut`. */
export interface BacktestSummary {
  run: BacktestRunResponse;
  total_signals: number;
  by_pattern: BacktestPatternBreakdown[];
  by_exit_reason: BacktestExitReasonBreakdown[];
}

// ---------------------------------------------------------------------------
// Escaneos disponibles
// ---------------------------------------------------------------------------

/** `BacktestAvailableScanOut`. Solo escaneos completados. */
export interface BacktestAvailableScan {
  id: string;
  symbol: string;
  timeframe: string;
  date_from: string;
  date_to: string;
  total_candles: number;
  total_occurrences: number;
}

/** `BacktestAvailableScansOut`. */
export interface BacktestAvailableScansOut {
  scans: BacktestAvailableScan[];
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------

export type BacktestLogLevel = "info" | "warning" | "error";

/** `BacktestLogOut`. El backend emite `progress` siempre, aunque sea `null`. */
export interface BacktestLog {
  id: string;
  timestamp: string;
  level: BacktestLogLevel;
  message: string;
  progress: number | null;
}
