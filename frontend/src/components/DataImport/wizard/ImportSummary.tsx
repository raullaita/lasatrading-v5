import type { ImportConfig } from "../../../types/dataImport";
import { formatDateEs } from "../../../utils/format";

export function ImportSummary({
  config,
  combinations,
}: {
  config: ImportConfig;
  combinations: number;
}) {
  const expectedCandles = Math.round(
    ((new Date(config.date_to).getTime() - new Date(config.date_from).getTime()) / 86_400_000) * combinations,
  ).toLocaleString("es");

  return (
    <div className="space-y-4">
      <SummaryRow label="Símbolos" value={config.symbols.join(", ") || "—"} />
      <SummaryRow label="Timeframes" value={config.timeframes.join(", ") || "—"} />
      <SummaryRow
        label="Período"
        value={`${formatDateEs(config.date_from)} → ${formatDateEs(config.date_to)}`}
      />
      <SummaryRow
        label="Modo"
        value={config.import_mode === "merge" ? "Merge" : config.import_mode === "append" ? "Append" : "Overwrite"}
      />
      <SummaryRow label="Combinaciones (símbolo × timeframe)" value={`${combinations}`} />
      <SummaryRow label="Velas estimadas" value={`~${expectedCandles}`} />
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
      <span className="text-sm text-slate-500 dark:text-slate-400">{label}</span>
      <span className="max-w-[60%] truncate text-sm font-medium text-slate-800 dark:text-slate-200" title={value}>
        {value}
      </span>
    </div>
  );
}