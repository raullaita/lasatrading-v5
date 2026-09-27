import { Plus, Trash2 } from "lucide-react";
import type { IndicatorConfig } from "../../types/features";

const AVAILABLE_INDICATORS = ["SMA", "EMA", "RSI", "MACD", "BBANDS", "ATR", "VOLUME_SMA"];

const DEFAULT_PARAMS: Record<string, Record<string, number>> = {
  SMA: { length: 20 },
  EMA: { length: 20 },
  RSI: { length: 14 },
  MACD: { fast: 12, slow: 26, signal: 9 },
  BBANDS: { length: 20, std: 2.0 },
  ATR: { length: 14 },
  VOLUME_SMA: { length: 20 },
};

const PARAM_LABELS: Record<string, Record<string, string>> = {
  SMA: { length: "Longitud" },
  EMA: { length: "Longitud" },
  RSI: { length: "Período" },
  MACD: { fast: "Rápida", slow: "Lenta", signal: "Señal" },
  BBANDS: { length: "Longitud", std: "Desv. estándar" },
  ATR: { length: "Período" },
  VOLUME_SMA: { length: "Longitud" },
};

export function IndicatorSelector({
  indicators,
  onChange,
}: {
  indicators: IndicatorConfig[];
  onChange: (indicators: IndicatorConfig[]) => void;
}) {
  const addIndicator = () => {
    const nextName =
      AVAILABLE_INDICATORS.find((n) => !indicators.some((i) => i.name === n)) ?? null;
    if (!nextName) return;
    onChange([...indicators, { name: nextName, params: { ...DEFAULT_PARAMS[nextName] } }]);
  };

  const removeIndicator = (index: number) => {
    onChange(indicators.filter((_, i) => i !== index));
  };

  const updateParam = (index: number, key: string, value: string) => {
    const num = parseFloat(value);
    if (isNaN(num)) return;
    const updated = indicators.map((ind, i) =>
      i === index ? { ...ind, params: { ...ind.params, [key]: num } } : ind,
    );
    onChange(updated);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {AVAILABLE_INDICATORS.map((name) => {
          const active = indicators.some((i) => i.name === name);
          return (
            <button
              key={name}
              type="button"
              onClick={() => {
                if (active) return;
                onChange([...indicators, { name, params: { ...DEFAULT_PARAMS[name] } }]);
              }}
              disabled={active}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                active
                  ? "bg-indigo-100 text-indigo-700 cursor-default dark:bg-indigo-950/40 dark:text-indigo-300"
                  : "border border-slate-300 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              }`}
            >
              {name}
            </button>
          );
        })}
      </div>

      {indicators.length > 0 && (
        <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
          {indicators.map((ind, idx) => (
            <div
              key={idx}
              className="flex items-center gap-2 rounded-lg bg-slate-50 p-2 dark:bg-slate-800"
            >
              <span className="flex-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                {ind.name}
              </span>
              {Object.entries(PARAM_LABELS[ind.name] ?? {}).map(([key, label]) => (
                <label key={key} className="text-xs text-slate-500 dark:text-slate-400">
                  {label}
                  <input
                    type="number"
                    value={ind.params[key] ?? ""}
                    onChange={(e) => updateParam(idx, key, e.target.value)}
                    className="ml-1 w-16 rounded border border-slate-300 px-1 py-0.5 text-xs focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    step="any"
                  />
                </label>
              ))}
              <button
                type="button"
                onClick={() => removeIndicator(idx)}
                className="rounded p-1 text-slate-400 hover:text-rose-600 dark:text-slate-500 dark:hover:text-rose-500"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={addIndicator}
        disabled={indicators.length >= AVAILABLE_INDICATORS.length}
        className="inline-flex items-center gap-1 rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 hover:border-indigo-500 hover:text-indigo-600 disabled:opacity-40 dark:border-slate-700 dark:text-slate-400 dark:hover:border-indigo-400 dark:hover:text-indigo-400"
      >
        <Plus className="h-3 w-3" /> Añadir indicador
      </button>
    </div>
  );
}
