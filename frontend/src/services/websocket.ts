import type { ImportLog } from "../types/dataImport";

export interface WebSocketHandlers {
  onLog: (log: ImportLog) => void;
  onConnectionChange?: (connected: boolean) => void;
  onError?: (message: string) => void;
}

interface ConnectionState {
  socket: WebSocket | null;
  retries: number;
  timer: number | null;
  handlers: WebSocketHandlers;
  closed: boolean;
}

const MAX_RECONNECTS = 5;
const BACKOFF_BASE_MS = 1000;
const active: Map<string, ConnectionState> = new Map();

function wsUrl(jobId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/api/v1/data-import/logs/${jobId}`;
}

/**
 * Conecta al WebSocket de logs de un job con reconexión automática (backoff
 * exponencial). Retorna una función para desconectar.
 */
export function connectJobLogs(jobId: string, handlers: WebSocketHandlers): () => void {
  const existing = active.get(jobId);
  if (existing) {
    existing.handlers = { ...existing.handlers, ...handlers };
    return () => disconnectJobLogs(jobId);
  }

  const state: ConnectionState = {
    socket: null,
    retries: 0,
    timer: null,
    handlers,
    closed: false,
  };
  active.set(jobId, state);

  const open = () => {
    if (state.closed) return;
    const socket = new WebSocket(wsUrl(jobId));
    state.socket = socket;

    socket.onopen = () => {
      state.retries = 0;
      state.handlers.onConnectionChange?.(true);
    };

    socket.onmessage = (event) => {
      try {
        state.handlers.onLog(JSON.parse(event.data as string) as ImportLog);
      } catch {
        // mensaje no parseable: se ignora
      }
    };

    socket.onclose = (event) => {
      state.socket = null;
      state.handlers.onConnectionChange?.(false);
      if (state.closed) return;
      // Un cierre limpio (código 1000) indica fin intencional (job terminal).
      if (event.wasClean && event.code === 1000) {
        active.delete(jobId);
        return;
      }
      if (state.retries < MAX_RECONNECTS) {
        state.retries += 1;
        const delay = Math.min(BACKOFF_BASE_MS * 2 ** (state.retries - 1), 10_000);
        state.timer = window.setTimeout(open, delay);
      } else {
        active.delete(jobId);
        state.handlers.onError?.("No se pudo mantener la conexión en tiempo real");
      }
    };

    socket.onerror = () => {
      socket.close();
    };
  };

  open();
  return () => disconnectJobLogs(jobId);
}

export function disconnectJobLogs(jobId: string): void {
  const state = active.get(jobId);
  if (!state) return;
  state.closed = true;
  if (state.timer !== null) window.clearTimeout(state.timer);
  state.socket?.close();
  active.delete(jobId);
}
