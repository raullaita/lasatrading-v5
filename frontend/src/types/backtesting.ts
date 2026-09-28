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
// Analisis y calibracion
// ---------------------------------------------------------------------------

/** Caja del histograma de una excursion, con los bordes en porcentaje. */
export interface ExcursionBucket {
  lower: string;
  upper: string;
  count: number;
}

/**
 * `ExcursionStatsOut`: distribucion de MAE o MFE de una poblacion.
 *
 * Ojo al signo y a las unidades, que son las dos trampas del modulo:
 *
 * * Los percentiles van **en porcentaje y positivos** para el MFE y tambien
 *   para el MAE, que viaja en valor absoluto. El backend convierte la
 *   fraccion de la columna (`0.012`) al leerla; si aqui se dividiera por 100
 *   otra vez, un MAE del 1,2% se pintaria como 0,012%.
 * * `capped_at_pct` es el nivel del run que recorta esta poblacion (el TP para
 *   las ganadoras, el SL para las perdedoras) e `is_capped` dice si los datos
 *   llegaron a tocarlo. Sin esto, un percentil 90 clavado en el TP se lee como
 *   una oportunidad de mercado cuando es el techo que se puso uno mismo.
 */
export interface ExcursionStats {
  count: number;
  p10: string | null;
  p25: string | null;
  p50: string | null;
  p75: string | null;
  p90: string | null;
  minimum: string | null;
  maximum: string | null;
  mean: string | null;
  buckets: ExcursionBucket[];
  capped_at_pct: string | null;
  is_capped: boolean;
}

/** `PatternCalibrationOut`: un patron en una direccion. */
export interface PatternCalibration {
  pattern_name: string;
  direction: TradeDirection;
  trades: number;
  wins: number;
  losses: number;
  /**
   * Operaciones cuyo cierre no lo decidio ningun nivel del run. De ahi salen
   * las propuestas, porque son las unicas sin techo puesto por el TP o el SL.
   */
  free_trades: number;
  winner_mfe: ExcursionStats;
  loser_mae: ExcursionStats;
  free_mfe: ExcursionStats;
  free_mae: ExcursionStats;
  suggested_take_profit_pct: string | null;
  /**
   * Siempre `null` en la version actual, y no por un hueco pendiente: el nivel
   * del stop no es calibrable con percentiles (ver `BacktestAnalysis`). El
   * barrido de parametros es quien lo mide.
   */
  suggested_stop_loss_pct: string | null;
  findings: string[];
  warnings: string[];
}

/** `BacktestAnalysisOut`. */
export interface BacktestAnalysis {
  run_id: string;
  strategy: BacktestRunResponse;
  trades: number;
  free_trades: number;
  pooled_mfe: ExcursionStats;
  pooled_mae: ExcursionStats;
  groups: PatternCalibration[];
  /**
   * Teorico, del percentil 50 de las operaciones que ningún nivel corto. Es un
   * punto de partida, no un optimo: la magnitud buena la dice el barrido.
   */
  suggested_take_profit_pct: string | null;
  suggested_stop_loss_pct: string | null;
  findings: string[];
  warnings: string[];
}

/** Peticion de `POST /{id}/sweep`. Un `null` es "sin ese nivel". */
export interface SweepGrid {
  take_profit_pcts: (number | null)[];
  stop_loss_pcts: (number | null)[];
  max_holds: number[];
}

/** `SweepPointOut`: una fila de la tabla comparativa. Nada de esto se guarda. */
export interface SweepPoint {
  take_profit_pct: string | null;
  stop_loss_pct: string | null;
  max_hold: number;
  total_trades: number;
  skipped_signals: number;
  net_pnl: string;
  total_return_pct: string;
  win_rate: string | null;
  profit_factor: string | null;
  max_drawdown_pct: string;
  sharpe_ratio: string | null;
  avg_bars_held: string | null;
  /** Reparto de motivos de cierre: explica *por que* cambia el resultado. */
  exits: Record<string, number>;
  /** `true` si la fila es la combinacion que ya usaba el run. */
  is_baseline: boolean;
}

/** `BacktestSweepOut`. */
export interface BacktestSweep {
  run_id: string;
  strategy: BacktestRunResponse;
  points: SweepPoint[];
  requested: number;
  simulated: number;
  elapsed_ms: number;
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
