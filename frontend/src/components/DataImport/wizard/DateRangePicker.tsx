import { useState } from "react";
import type { ChangeEvent } from "react";

export interface DateRange {
  from: string;
  to: string;
}

const PRESETS = [
  { key: "1m", label: "1 mes", months: 1 },
  { key: "3m", label: "3 meses", months: 3 },
  { key: "1y", label: "1 año", months: 12 },
  { key: "2y", label: "2 años", months: 24 },
];

const pad2 = (n: number) => n.toString().padStart(2, "0");

function toLocalInput(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function startOfDay(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addMonths(date: Date, months: number): Date {
  const result = new Date(date);
  const day = result.getDate();
  result.setDate(1);
  result.setMonth(result.getMonth() + months);
  const lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
  result.setDate(Math.min(day, lastDay));
  return result;
}

export function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const [activePreset, setActivePreset] = useState<string | null>(() => {
    const match = PRESETS.find((p) => {
      const to = new Date();
      const from = addMonths(startOfDay(to), -p.months);
      return toLocalInput(from) === value.from && toLocalInput(to) === value.to;
    });
    return match?.key ?? null;
  });

  const applyPreset = (key: string, months: number) => {
    const to = new Date();
    const from = addMonths(startOfDay(to), -months);
    setActivePreset(key);
    onChange({ from: toLocalInput(from), to: toLocalInput(to) });
  };

  const onManualChange = (field: "from" | "to") => (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.value) return;
    setActivePreset(null);
    onChange({ ...value, [field]: e.target.value });
  };

  const today = toLocalInput(new Date());

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => applyPreset(p.key, p.months)}
            className={
              activePreset === p.key
                ? "rounded-lg border border-indigo-600 bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white"
                : "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            }
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Desde
          </span>
          <input
            type="date"
            value={value.from}
            max={today}
            onChange={onManualChange("from")}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-indigo-900"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Hasta
          </span>
          <input
            type="date"
            value={value.to}
            max={today}
            onChange={onManualChange("to")}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-indigo-900"
          />
        </label>
      </div>
      {value.from >= value.to && (
        <p className="text-sm text-rose-600">La fecha "desde" debe ser anterior a "hasta".</p>
      )}
    </div>
  );
}
