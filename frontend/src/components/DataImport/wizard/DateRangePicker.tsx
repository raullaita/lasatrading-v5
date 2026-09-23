export interface DateRange {
  from: string;
  to: string;
}

const PRESETS = [
  { label: "1 mes", months: 1 },
  { label: "3 meses", months: 3 },
  { label: "1 año", months: 12 },
  { label: "2 años", months: 24 },
];

export function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const applyPreset = (months: number) => {
    const to = new Date();
    const from = new Date(to);
    from.setMonth(from.getMonth() - months);
    onChange({ from: toISO(from), to: toISO(to) });
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => applyPreset(p.months)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Desde</span>
          <input
            type="date"
            value={value.from.slice(0, 10)}
            onChange={(e) => onChange({ ...value, from: toISO(new Date(`${e.target.value}T00:00:00`)) })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Hasta</span>
          <input
            type="date"
            value={value.to.slice(0, 10)}
            onChange={(e) => onChange({ ...value, to: toISO(new Date(`${e.target.value}T23:59:59`)) })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          />
        </label>
      </div>
      {value.from >= value.to && (
        <p className="text-sm text-rose-600">La fecha "desde" debe ser anterior a "hasta".</p>
      )}
    </div>
  );
}

function toISO(date: Date): string {
  return date.toISOString();
}