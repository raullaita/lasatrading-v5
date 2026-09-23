import type { ImportMode } from "../../../types/dataImport";

const MODES: { value: ImportMode; title: string; description: string }[] = [
  {
    value: "merge",
    title: "Merge (recomendado)",
    description: "Inserta velas nuevas y actualiza solo las que cambiaron. Ideal para reimportaciones.",
  },
  {
    value: "append",
    title: "Append",
    description: "Solo inserta velas nuevas; ignora las existentes aunque difieran.",
  },
  {
    value: "overwrite",
    title: "Overwrite",
    description: "Borra el rango de velas del símbolo y timeframe, luego inserta desde cero.",
  },
];

export function ImportOptions({
  value,
  onChange,
}: {
  value: ImportMode;
  onChange: (mode: ImportMode) => void;
}) {
  return (
    <div className="space-y-3">
      {MODES.map((mode) => {
        const active = value === mode.value;
        return (
          <button
            key={mode.value}
            type="button"
            onClick={() => onChange(mode.value)}
            className={`w-full rounded-xl border p-4 text-left transition-colors ${
              active
                ? "border-indigo-600 bg-indigo-50"
                : "border-slate-200 bg-white hover:bg-slate-50"
            }`}
          >
            <p className={`text-sm font-semibold ${active ? "text-indigo-700" : "text-slate-800"}`}>
              {mode.title}
            </p>
            <p className="mt-1 text-sm text-slate-500">{mode.description}</p>
          </button>
        );
      })}
    </div>
  );
}