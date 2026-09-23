import { DEFAULT_TIMEFRAMES, TIMEFRAME_GROUPS } from "./timeframes";

export function TimeframeSelector({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (timeframes: string[]) => void;
}) {
  const toggle = (tf: string) => {
    onChange(selected.includes(tf) ? selected.filter((t) => t !== tf) : [...selected, tf]);
  };

  const useDefaults = () => onChange(DEFAULT_TIMEFRAMES);

  return (
    <div className="space-y-4">
      {TIMEFRAME_GROUPS.map((group) => (
        <div key={group.label}>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-700">{group.label}</p>
            <span className="text-xs text-slate-400">
              {group.data.filter((tf) => selected.includes(tf)).length} seleccionados
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {group.data.map((tf) => {
              const active = selected.includes(tf);
              return (
                <button
                  key={tf}
                  type="button"
                  onClick={() => toggle(tf)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    active
                      ? "border-indigo-600 bg-indigo-600 text-white"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {tf}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={useDefaults}
        className="text-xs font-medium text-indigo-600 hover:underline"
      >
        Usar defaults (1h, 4h, 1d)
      </button>
    </div>
  );
}