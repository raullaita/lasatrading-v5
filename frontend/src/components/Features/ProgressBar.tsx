export function ProgressBar({
  current,
  total,
  label = "Progreso",
}: {
  current: number;
  total: number;
  label?: string;
}) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{label}</span>
        <span className="font-medium text-slate-700 dark:text-slate-200">{clamped}%</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
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
