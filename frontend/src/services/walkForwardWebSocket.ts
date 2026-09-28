import type { WalkForwardLog } from "../types/walkForward";

/**
 * Suscripcion a los logs de un walk-forward por WebSocket.
 *
 * Clon de `backtestsWebSocket`: el backend no hace push, sondea
 * `walk_forward_logs` cada segundo desde el ultimo offset enviado y cierra la
 * conexion (1000) cuando el run llega a un estado terminal. Se puede conectar a
 * un run en marcha o ya terminado y llega todo el historico.
 *
 * Va a una tabla de logs propia y no a la del backtest porque
 * `backtest_logs` tiene clave foranea a `backtest_runs`: un walk-forward no es
 * un backtest y no puede escribir sus lineas de progreso ahi. La consecuencia
 * practica es que las dos conexiones se distinguen solo por el `runId` de la
 * clave, y por eso el mapa de conexiones activas no se comparte con el del
 * backtest: un UUID de run no puede aparecer en los dos, y si compartieran el
 * mapa, dos pantallas del mismo simbolo se pisarian.
 */

export interface WalkForwardLogHandlers {
  onLog: (log: WalkForwardLog) => void;
  onConnectionChange?: (connected: boolean) => void;
  onError?: (message: string) => void;
}

interface ConnectionState {
  socket: WebSocket | null;
  retries: number;
  timer: number | null;
  handlers: WalkForwardLogHandlers;
  closed: boolean;
}

const MAX_RECONNECTS = 5;
const BACKOFF_BASE_MS = 1000;

/** Conexiones vivas por `runId` (el StrictMode en desarrollo no duplica). */
const active: Map<string, ConnectionState> = new Map();

function wsUrl(runId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/api/v1/walk-forward/runs/${runId}/logs`;
}

export function connectWalkForwardLogs(
  runId: string,
  handlers: WalkForwardLogHandlers,
): () => void {
  const existing = active.get(runId);
  if (existing) {
    existing.handlers = { ...existing.handlers, ...handlers };
    return () => disconnectWalkForwardLogs(runId);
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
        const payload = JSON.parse(event.data as string) as WalkForwardLog | { error: string };
        // El backend manda «run not found» y cierra si el run no existe. Sin
        // esta rama caeria en `onLog` y la UI pintaria un log sin `level`.
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
      // Cierre limpio: el backend lo hizo porque el run esta en estado terminal.
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
  return () => disconnectWalkForwardLogs(runId);
}

export function disconnectWalkForwardLogs(runId: string): void {
  const state = active.get(runId);
  if (!state) return;
  state.closed = true;
  if (state.timer !== null) window.clearTimeout(state.timer);
  state.socket?.close();
  active.delete(runId);
}
