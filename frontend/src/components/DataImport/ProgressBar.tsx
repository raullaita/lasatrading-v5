export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
        <span>{label ?? "Progreso"}</span>
        <span className="font-medium text-slate-700">{clamped}%</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            clamped >= 100 ? "bg-emerald-500" : "bg-indigo-500"
          }`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}