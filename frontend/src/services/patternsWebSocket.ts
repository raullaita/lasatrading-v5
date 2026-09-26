import type { PatternScanLog } from "../types/patterns";

/**
 * Suscripcion a los logs de un escaneo por WebSocket.
 *
 * El backend no hace push: mantiene abierta la conexion y cada segundo sondea
 * la tabla `pattern_scan_logs` desde el ultimo offset que ha enviado
 * (`offset += len(logs)`). Asi el cliente puede conectarse a un job ya en
 * marcha o ya terminado y recibe igual todo el historico, en vez de solo lo
 * que se emita a partir de ahora. Cuando el job entra en estado terminal hace
 * `websocket.close()`, y ahi se corta sola la conexion.
 */

export interface PatternLogHandlers {
  onLog: (log: PatternScanLog) => void;
  onConnectionChange?: (connected: boolean) => void;
  onError?: (message: string) => void;
}

interface ConnectionState {
  socket: WebSocket | null;
  retries: number;
  timer: number | null;
  handlers: PatternLogHandlers;
  closed: boolean;
}

const MAX_RECONNECTS = 5;
const BACKOFF_BASE_MS = 1000;

/**
 * Conexiones vivas por `jobId`.
 *
 * El mapa es lo que hace idempotente la funcion: montar dos veces el mismo
 * componente de detalle no abre dos sockets al mismo job, actualiza los
 * handlers del existente. Sin esto, un React StrictMode en desarrollo
 * duplicaria cada suscripcion.
 */
const active: Map<string, ConnectionState> = new Map();

/**
 * La URL se deriva de `window.location`, no se fija a `localhost:8000`.
 *
 * El prefijo `/ws` lo consume el proxy de Vite, que lo quita antes de enviarlo
 * al backend (`rewrite: (path) => path.replace(/^\\/ws/, "")`). Asi el mismo
 * codigo funciona en desarrollo, en produccion detras de un subdominio y con
 * `https:`, donde el protocolo tiene que pasar a `wss:` o el navegador
 * bloquea la conexion como mixed content.
 */
function wsUrl(jobId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/api/v1/patterns/scans/${jobId}/logs`;
}

/**
 * Conecta al WebSocket de logs de un escaneo, con reconexion automatica y
 * backoff exponencial (1 s, 2 s, 4 s, 8 s, 10 s tope). Retorna la funcion de
 * desconexion.
 *
 * Reconecta solo ante cierres no limpios. Un cierre con codigo 1000 es el
 * backend diciendo "el job termino", y reintentar seria gastar los cinco
 * reintentos para volver a recibir lo mismo.
 */
export function connectPatternScanLogs(jobId: string, handlers: PatternLogHandlers): () => void {
  const existing = active.get(jobId);
  if (existing) {
    existing.handlers = { ...existing.handlers, ...handlers };
    return () => disconnectPatternScanLogs(jobId);
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
        const payload = JSON.parse(event.data as string) as PatternScanLog | { error: string };
        // El backend manda este objeto y cierra si el job no existe. Sin esta
        // rama caeria en el `onLog` y la UI intentaria pintar un log con
        // `level` undefined.
        if ("error" in payload) {
          state.handlers.onError?.(payload.error);
          return;
        }
        state.handlers.onLog(payload);
      } catch {
        // Mensaje no parseable: se ignora. Un log corrupto no debe tumbar la
        // vista de progreso, que es lo que el usuario esta mirando.
      }
    };

    socket.onclose = (event) => {
      state.socket = null;
      state.handlers.onConnectionChange?.(false);
      if (state.closed) return;
      // Cierre limpio: el backend lo hizo porque el job esta en estado
      // terminal. No hay nada que reconectar.
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
      // `onclose` llega siempre despues y es ahi donde se decide si reintentar;
      // cerrar aqui solo evita dejar el socket colgado.
      socket.close();
    };
  };

  open();
  return () => disconnectPatternScanLogs(jobId);
}

/**
 * Cierra la conexion y cancela cualquier reconexion pendiente.
 *
 * Marca `closed` antes de cerrar para que el `onclose` que dispara el propio
 * `close()` no lo interprete como una caida y programa un reintento sobre un
 * socket que el componente ya no quiere.
 */
export function disconnectPatternScanLogs(jobId: string): void {
  const state = active.get(jobId);
  if (!state) return;
  state.closed = true;
  if (state.timer !== null) window.clearTimeout(state.timer);
  state.socket?.close();
  active.delete(jobId);
}
