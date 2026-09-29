/**
 * Tipos del modulo de alertas.
 *
 * Contrato espejo de `backend/app/modules/alerts/schemas.py` (a traves de los
 * `Out` del router). Los numeros llegan como **string** porque el backend los
 * persiste en `Numeric`: un `0.1` en JSON con coma flotante es
 * `0.1000000000000000055`, y multiplicar por cien ahi produce
 * `10.000000000000002`, que en pantalla es un porcentaje con basura.
 */

/**
 * El estado de validacion, que **no** es el estado del job y no vive en
 * `StatusBadge`.
 *
 * Va en su propio tipo, y a propósito. Un badge de «completed» verde al lado de
 * un «descartada» rojo dirían que un run terminó y una configuración perdió, que
 * son dos cosas que se confunden en la mirada y que aquí están separadas.
 */
export type AlertValidationStatus = "sostenida" | "prometedora" | "descartada" | "sin_evaluar";

/**
 * Si el informe de respaldo llegó a simular el patrón de la regla.
 *
 * Es una pregunta **distinta** del veredicto, y la que más se confunde con él: un
 * informe sobre un escaneo de cuatro patrones puede salir `sostenida` y no haber
 * mirado jamás el patrón del que alerta la regla. Un veredicto alto con
 * cobertura `fuera_de_filtro` no dice nada sobre ese patrón.
 */
export type AlertPatternCoverage = "cubierto" | "fuera_de_filtro" | "sin_informe";

export type AlertDeliveryStatus = "pending" | "sent" | "failed" | "skipped";

/**
 * `skipped` no es `failed`, y la diferencia es toda la auditoría.
 *
 * `skipped` es «no se intentó porque el canal estaba apagado»; `failed` es «se
 * intentó y no llegó». Sin esa distinción, apagar el sistema y tener un fallo de
 * red producen el mismo estado, y no hay forma de responder a la única pregunta
 * que importa: ¿llegó?
 */
export const ALERT_STATUS_LABELS: Record<AlertDeliveryStatus, string> = {
  pending: "Pendiente",
  sent: "Enviada",
  failed: "No entregada",
  skipped: "No se intentó",
};

export interface AlertStrategy {
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_hold: number | null;
  /**
   * `false` en informes anteriores a que se guardara la comisión. Se declara
   * desconocido en vez de asumir un valor: un informe que no dice con qué costes
   * se simuló, no lo dice.
   */
  base_known: boolean;
}

export interface AlertRule {
  id: string;
  name: string;
  symbol: string;
  timeframe: string;
  pattern_name: string;
  direction: "bullish" | "bearish";
  config: AlertStrategy;
  validation_status: AlertValidationStatus;
  /** La frase que va al mensaje. La escribe el backend, nunca el cliente. */
  validation_note: string | null;
  pattern_coverage: AlertPatternCoverage;
  enabled: boolean;
  cooldown_minutes: number;
  walk_forward_run_id: string | null;
  candidate_rank: number | null;
  backing_oi_low: number | null;
  backing_oi_high: number | null;
  backing_oos_return_pct: number | null;
  backing_market_return_pct: number | null;
  backing_windows: number | null;
  backing_created_at: string;
  last_alerted_at: string | null;
  last_evaluated_at: string | null;
  /**
   * Por qué ruta se evaluó la regla y qué encontró. Sin esto, «no ha saltado» y
   * «no se ha mirado» son la misma línea en blanco.
   */
  last_evaluation_note: string | null;
  created_at: string;
}

/**
 * Petición de alta.
 *
 * **No acepta `take_profit_pct`, `stop_loss_pct` ni `max_hold`**, y no es un
 * olvido: si los admitiera, se podría decir «respaldada por el informe X» y
 * guardar otros niveles, y el aviso llevaría las credenciales de un experimento
 * y los números de otro.
 */
export interface AlertRuleCreateIn {
  name: string;
  pattern_name: string;
  direction: "bullish" | "bearish";
  /** Solo hacen falta sin informe, que es cuando no hay escaneo de donde deducirlos. */
  symbol?: string | null;
  timeframe?: string | null;
  walk_forward_run_id?: string | null;
  candidate_rank?: number | null;
  cooldown_minutes?: number;
}

export interface Alert {
  id: string;
  rule_id: string;
  signal_timestamp: string;
  pattern_name: string;
  direction: string;
  symbol: string;
  timeframe: string;
  /**
   * Cierre de la vela de la señal. **No es el precio de entrada**: la entrada es
   * la apertura de T+1, que cuando se detecta el patrón no ha ocurrido. Por eso
   * el campo se llama `reference_price` y en pantalla «referencia».
   */
  reference_price: string;
  status: AlertDeliveryStatus;
  telegram_message_id: number | null;
  delivery_error: string | null;
  attempts: number;
  sent_at: string | null;
  /** El texto exacto que salió. Telegram deja editar mensajes. */
  message_text: string | null;
  detected_at: string;
}

export interface AlertListOut {
  alerts: Alert[];
  total: number;
}

export interface TelegramProbeOut {
  ok: boolean;
  skipped: boolean;
  message_id: number | null;
  error: string | null;
  /** El backend dice cómo arreglarlo. Un canal roto que no dice por qué no se arregla. */
  pista: string | null;
}
