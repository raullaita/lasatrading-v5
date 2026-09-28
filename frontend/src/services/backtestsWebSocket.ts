import type { BacktestLog } from "../types/backtesting";

/**
 * Suscripcion a los logs de un run por WebSocket.
 *
 * Clon de `patternsWebSocket`: el backend no hace push, sondea
 * `backtest_logs` cada segundo desde el ultimo offset enviado y cierra la
 * conexion (1000) cuando el run llega a un estado terminal. Cliente puede
 * conectarse a un run en marcha o ya terminado y recibe todo el historico.
 */

export interface BacktestLogHandlers {
  onLog: (log: BacktestLog) => void;
  onConnectionChange?: (connected: boolean) => void;
  onError?: (message: string) => void;
}

interface ConnectionState {
  socket: WebSocket | null;
  retries: number;
  timer: number | null;
  handlers: BacktestLogHandlers;
  closed: boolean;
}

const MAX_RECONNECTS = 5;
const BACKOFF_BASE_MS = 1000;

/** Conexiones vivas por `runId` (el StrictMode en desarrollo no duplica). */
const active: Map<string, ConnectionState> = new Map();

function wsUrl(runId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/api/v1/backtests/${runId}/logs`;
}

export function connectBacktestLogs(runId: string, handlers: BacktestLogHandlers): () => void {
  const existing = active.get(runId);
  if (existing) {
    existing.handlers = { ...existing.handlers, ...handlers };
    return () => disconnectBacktestLogs(runId);
  }

  const state: ConnectionState = {
    socket: null,
    retries: 0,
    timer: null,
    handlers,
    closed: false,
  };
  active.set(runId, state);

  const open = () => {
    if (state.closed) return;
    const socket = new WebSocket(wsUrl(runId));
    state.socket = socket;

    socket.onopen = () => {
      state.retries = 0;
      state.handlers.onConnectionChange?.(true);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data as string) as BacktestLog | { error: string };
        // El backend manda «run not found» y cierra si el run no existe. Sin
        // esta rama caeria en `onLog` y la UI pintaria un log sin level.
        if ("error" in payload) {
          state.handlers.onError?.(payload.error);
          return;
        }
        state.handlers.onLog(payload);
      } catch {
        // Mensaje no parseable: se ignora. Un log corrupto no debe tumbar la
        // vista del run, que es lo que el usuario esta mirando.
      }
    };

    socket.onclose = (event) => {
      state.socket = null;
      state.handlers.onConnectionChange?.(false);
      if (state.closed) return;
      // Cierre limpio: el backend lo hizo porque el run esta en estado
      // terminal. No hay nada que reconectar.
      if (event.wasClean && event.code === 1000) {
        active.delete(runId);
        return;
      }
      if (state.retries < MAX_RECONNECTS) {
        state.retries += 1;
        const delay = Math.min(BACKOFF_BASE_MS * 2 ** (state.retries - 1), 10_000);
        state.timer = window.setTimeout(open, delay);
      } else {
        active.delete(runId);
        state.handlers.onError?.("No se pudo mantener la conexión en tiempo real");
      }
    };

    socket.onerror = () => {
      // `onclose` llega siempre despues y decide si reintentar; cerrar aqui
      // solo evita dejar el socket colgado.
      socket.close();
    };
  };

  open();
  return () => disconnectBacktestLogs(runId);
}

export function disconnectBacktestLogs(runId: string): void {
  const state = active.get(runId);
  if (!state) return;
  state.closed = true;
  if (state.timer !== null) window.clearTimeout(state.timer);
  state.socket?.close();
  active.delete(runId);
}
