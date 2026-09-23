import { useEffect, useRef } from "react";

import type { ImportLog, LogLevel } from "../../types/dataImport";

const levelStyles: Record<LogLevel, string> = {
  info: "text-slate-700",
  warning: "text-amber-600",
  error: "text-rose-600",
};

export function LogViewer({ logs, maxLines = 500 }: { logs: ImportLog[]; maxLines?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  const visible = logs.slice(-maxLines);

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Logs en vivo</p>
        <span className="text-xs text-slate-500">
          {visible.length}/{logs.length}
        </span>
      </div>
      <div
        ref={containerRef}
        className="h-64 overflow-y-auto p-3 font-mono text-xs leading-5"
      >
        {visible.length === 0 && (
          <p className="text-slate-600">Esperando eventos de importación…</p>
        )}
        {visible.map((log) => (
          <div key={log.id} className="flex gap-2">
            <span className="shrink-0 text-slate-500">
              {new Date(log.timestamp).toLocaleTimeString()}
            </span>
            <span className={levelStyles[log.level] ?? "text-slate-300"}>{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}