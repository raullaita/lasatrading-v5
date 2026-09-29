/**
 * Suscripcion a las alertas en vivo.
 *
 * A diferencia de los demas WebSocket del proyecto, este **no** manda el aviso
 * entero: manda el `alert_id` y el cliente pide lo que le falte por HTTP. La
 * razon es que mandar la fila por el socket significaria que lo que se ve en
 * pantalla y lo que hay en la base pueden divergir si una se actualiza entre los
 * dos, y lo que se quiere evitar es justo ver un aviso con un estado distinto
 * del que tiene guardado.
 *
 * Por eso el estado de entrega es parte de la historia y no un detalle: una
 * alerta detectada que **no** llegó es informacion distinta de una que sí, y el
 * cliente tiene que poder distinguirlo sin recargar.
 */

/** Lo que llega por el socket. Deliberadamente minimo. */
export interface AlertStreamHandlers {
  onAlert: (alertId: string) => void;
  onConnectionChange?: (connected: boolean) => void;
  onError?: (message: string) => void;
}

interface ConnectionState {
  socket: WebSocket | null;
  retries: number;
  timer: number | null;
  handlers: AlertStreamHandlers;
  closed: boolean;
}

const MAX_RECONNECTS = 5;
const BACKOFF_BASE_MS = 1000;

/** Suscripcion unica a todo el flujo, no por regla ni por alerta. */
let estado: ConnectionState | null = null;

function wsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/api/v1/alerts/stream`;
}

export function connectAlertStream(handlers: AlertStreamHandlers): () => void {
  // Una sola conexion para toda la aplicacion. Montar el componente dos veces no
  // abre dos sockets: el StrictMode en desarrollo monta dos veces y sin esto cada
  // alerta llegaria duplicada a la pantalla.
  if (estado) {
    estado.handlers = { ...estado.handlers, ...handlers };
    return disconnectAlertStream;
  }

  estado = { socket: null, retries: 0, timer: null, handlers, closed: false };

  const abrir = () => {
    if (!estado || estado.closed) return;
    const socket = new WebSocket(wsUrl());
    estado.socket = socket;

    socket.onopen = () => {
      if (estado) estado.retries = 0;
      handlers.onConnectionChange?.(true);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data as string) as { alert_id: string };
        handlers.onAlert(payload.alert_id);
      } catch {
        // Mensaje no parseable: se ignora. Un aviso corrupto no debe tumbar la
        // lista, que es lo que el usuario esta mirando.
      }
    };

    socket.onclose = (event) => {
      if (estado) estado.socket = null;
      handlers.onConnectionChange?.(false);
      if (!estado || estado.closed) return;
      if (event.wasClean && event.code === 1000) {
        estado = null;
        return;
      }
      if (estado.retries < MAX_RECONNECTS) {
        estado.retries += 1;
        const espera = Math.min(BACKOFF_BASE_MS * 2 ** (estado.retries - 1), 10_000);
        estado.timer = window.setTimeout(abrir, espera);
      } else {
        estado = null;
        handlers.onError?.("No se pudo mantener la conexión en tiempo real");
      }
    };

    socket.onerror = () => {
      // `onclose` llega siempre despues y decide si reintentar; cerrar aqui
      // solo evita dejar el socket colgado.
      socket.close();
    };
  };

  abrir();
  return disconnectAlertStream;
}

export function disconnectAlertStream(): void {
  if (!estado) return;
  estado.closed = true;
  if (estado.timer !== null) window.clearTimeout(estado.timer);
  estado.socket?.close();
  estado = null;
}
