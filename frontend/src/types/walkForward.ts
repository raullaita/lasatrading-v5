/**
 * Tipos del modulo de walk-forward.
 *
 * Contrato espejo de `backend/app/modules/backtesting/schemas.py`. Los numeros
 * llegan como **string** porque el backend los persiste en `Numeric` y los
 * serializa como decimal: un `0.1` en JSON con coma flotante es `0.1000000000000000055`,
 * y multiplicar por cien ahi produce 10.000000000000002, que se ve en pantalla
 * como un porcentaje con basura. Se convierten con `toNumber` al usarlos.
 */

export type WalkForwardRunStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

/**
 * Los tres grados de la §5.2. `descartada` va la ultima a proposito: el orden
 * del enum es el orden en que se muestran, y una combinacion descartada debajo
 * de una prometedora es exactamente como se leen.
 */
export type WalkForwardVerdict = "sostenida" | "prometedora" | "descartada";

export interface WalkForwardGrid {
  take_profit_pcts: (number | null)[];
  stop_loss_pcts: (number | null)[];
  max_holds: number[];
}

/** Configuracion de ventanas y guardas. El backend la congela al crear el run. */
export interface WalkForwardConfig {
  window_days: number;
  oos_days: number;
  step_days: number;
  min_windows: number;
  min_trades: number;
  holdout_days: number;
  beats_market_ratio: number;
  regimes_declared: number;
  max_simulations: number;
  minutes_per_candle: number;
  symbol: string;
  timeframe: string;
}

export interface WalkForwardCreateIn {
  scan_job_id: string;
  grid: WalkForwardGrid;
  window_days: number;
  oos_days: number;
  step_days: number;
  min_windows: number;
  min_trades: number;
  holdout_days: number;
  beats_market_ratio: number;
  /**
   * Regimenes declarados por el usuario. Es una declaracion, no una deteccion:
   * el motor no sabe si los datos son un lateral, un Bajista o tres trozos
   * pegados, y `sostenida` exige tres. Sin esto, el campo no se puede rellenar
   * honestamente.
   */
  regimes_declared: number;
  max_simulations: number;
}

export interface WalkForwardRun {
  id: string;
  scan_job_id: string;
  status: WalkForwardRunStatus;
  config: WalkForwardConfig;
  /** La rejilla guardada trae `combinations`, que el backend ya sabe contar. */
  grid: WalkForwardGrid & { combinations: number };
  initial_capital: string;
  /** Regla 4 del Contrato Estadistico: combinaciones evaluadas, no filas guardadas. */
  simulations: number;
  windows: number;
  windows_without_selection: number;
  equity_final: string | null;
  oos_return_pct: string | null;
  market_return_pct: string | null;
  max_drawdown_pct: string | null;
  elapsed_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface WalkForwardRunListOut {
  runs: WalkForwardRun[];
  total: number;
}

export interface WalkForwardSelectedStrategy {
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_hold: number;
}

export interface WalkForwardWindow {
  index: number;
  is_from: string;
  is_to: string;
  oos_from: string;
  oos_to: string;
  selected_strategy: WalkForwardSelectedStrategy;
  is_sharpe: string | null;
  oos_trades: number;
  oos_evaluated: number;
  oos_return_pct: string;
  oos_net_pnl: string;
  oos_equity_final: string;
  oos_win_rate: string | null;
  oos_sharpe: string | null;
  oos_max_drawdown_pct: string;
  market_return_pct: string;
  market_max_drawdown_pct: string;
  exits: Record<string, number>;
}

export interface WalkForwardCandidate {
  rank: number;
  take_profit_pct: string | null;
  stop_loss_pct: string | null;
  max_hold: number;
  windows: number;
  trades: number;
  oos_return_pct: string;
  market_return_pct: string;
  win_rate_mean: string;
  sharpe_mean: string;
  sharpe_dispersion: string;
  max_drawdown_worst: string;
  consistency: string;
  beats_market_windows: number;
  profitable_windows: number;
  score: string;
  verdict: WalkForwardVerdict;
  /**
   * IC95% del retorno OOS compuesto. `null` para una candidata descartada por
   * no llegar al minimo de operaciones: un intervalo de confianza de una muestra
   * que no existe invites a creerselo, asi que se pinta como guion y no como
   * "no lo sé todavia".
   */
  ci95_low: string | null;
  ci95_high: string | null;
  rejections: string[];
  notes: string[];
}

export interface WalkForwardReport {
  run: WalkForwardRun;
  windows: WalkForwardWindow[];
  candidates: WalkForwardCandidate[];
}

export interface WalkForwardEquityPoint {
  timestamp: string;
  equity: string;
  market_equity: string;
  drawdown_pct: string;
  /** Que ventana estaba abierta en esta vela, para contrastar con la tabla. */
  window_index: number;
}

export interface WalkForwardEquitySeries {
  points: WalkForwardEquityPoint[];
  /** Velas reales de la curva. Distinto de `returned` cuando hay submuestreo. */
  total_points: number;
  returned: number;
  max_drawdown_pct: string | null;
}

export type WalkForwardLogLevel = "info" | "warning" | "error";

export interface WalkForwardLog {
  id: string;
  run_id: string;
  timestamp: string;
  level: WalkForwardLogLevel;
  message: string;
  /** Ventanas terminadas, en [0, 100]. `null` en las lineas que no son avance. */
  progress: number | null;
}
