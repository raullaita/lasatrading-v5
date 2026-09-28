import { useEffect, useRef } from "react";
import type { WalkForwardLog } from "../../types/walkForward";

/**
 * Consola de logs del walk-forward en vivo, alimentada por el WebSocket.
 *
 * Gemela de `BacktestLogViewer`, y se duplica a proposito por el mismo motivo:
 * el tipo de log es otro y mezclarlos obligaria a un componente de este modulo
 * a importar tipos del de backtesting.
 *
 * Aqui `progress` **si** llega con valor, y a diferencia del backtest es una
 * barra de verdad: el motor reporta por ventana, que es una unidad que el
 * usuario entiende ("van cuatro de diez"), y no por simulacion. Por eso la
 * cabecera la pinta como barra y no como un porcentaje suelto.
 */

const levelStyles: Record<WalkForwardLog["level"], string> = {
  info: "text-slate-300",
  warning: "text-amber-400",
  error: "text-rose-400",
};

/** Líneas que se pintan. Por encima de 500 los nodos se notan en el scroll. */
const MAX_LINES = 500;

export function WalkForwardLogViewer({
  logs,
  connected,
  maxLines = MAX_LINES,
}: {
  logs: WalkForwardLog[];
  connected: boolean;
  maxLines?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  const visible = logs.slice(-maxLines);
  const progreso = logs.reduce<number | null>(
    (max, log) => (log.progress === null ? max : Math.max(max ?? 0, log.progress)),
    null,
  );

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-950 dark:border-slate-800">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Logs del walk-forward
        </p>
        <div className="flex items-center gap-3">
          {progreso !== null && (
            <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full bg-blue-500 transition-[width] duration-300"
                style={{ width: `${Math.min(100, progreso)}%` }}
              />
            </div>
          )}
          <span className={`text-xs ${connected ? "text-emerald-500" : "text-slate-500"}`}>
            {connected ? "en vivo" : "sin conexión"}
          </span>
          <span className="text-xs text-slate-500">
            {visible.length}/{logs.length}
          </span>
        </div>
      </div>
      <div ref={containerRef} className="h-64 overflow-y-auto p-3 font-mono text-xs leading-5">
        {visible.length === 0 && <p className="text-slate-600">Esperando logs del walk-forward…</p>}
        {visible.map((log) => (
          <div key={log.id} className="flex gap-2">
            <span className="shrink-0 text-slate-500">
              {new Date(log.timestamp).toLocaleTimeString("es-ES")}
            </span>
            <span className={levelStyles[log.level] ?? "text-slate-300"}>
              [{log.level.toUpperCase()}] {log.message}
              {log.progress !== null && <span className="text-slate-500"> ({log.progress}%)</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
