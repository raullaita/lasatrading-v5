import { useEffect, useRef } from "react";
import type { PatternScanLog } from "../../types/patterns";

/**
 * Consola de logs del escaneo en vivo, alimentada por el WebSocket.
 *
 * A diferencia del de Features, este muestra además el `progress` de cada línea
 * aunque no sea un log de avance, porque en un escaneo el progreso solo aparece
 * en algunos mensajes y verlo pegado a la línea explica de un vistazo por qué
 * un job parece atascado.
 */

const levelStyles: Record<PatternScanLog["level"], string> = {
  info: "text-slate-300",
  warning: "text-amber-400",
  error: "text-rose-400",
};

/** Líneas que se pintan. Por encima de 500 los nodos se notan en el scroll. */
const MAX_LINES = 500;

export function LogViewer({
  logs,
  maxLines = MAX_LINES,
}: {
  logs: PatternScanLog[];
  maxLines?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  const visible = logs.slice(-maxLines);

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-950 dark:border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Logs en vivo</p>
        <span className="text-xs text-slate-500">
          {visible.length}/{logs.length}
        </span>
      </div>
      <div ref={containerRef} className="h-64 overflow-y-auto p-3 font-mono text-xs leading-5">
        {visible.length === 0 && <p className="text-slate-600">Esperando logs del escaneo…</p>}
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
