import type { ImportStats } from "../../types/dataImport";
import { ProgressBar } from "./ProgressBar";

const formatNumber = (n: number) => n.toLocaleString("es");

export function StatsPanel({ stats }: { stats: ImportStats | null }) {
  if (!stats) return null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Descargadas" value={formatNumber(stats.total_candles_downloaded)} />
        <StatCard label="Insertadas" value={formatNumber(stats.total_candles_inserted)} accent />
        <StatCard label="Actualizadas" value={formatNumber(stats.total_candles_updated)} />
        <StatCard label="Idénticas (skip)" value={formatNumber(stats.total_candles_skipped)} />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Combinaciones ok" value={`${stats.combinations_completed}`} />
        <StatCard
          label="Combinaciones fallidas"
          value={`${stats.combinations_failed}`}
          danger={stats.combinations_failed > 0}
        />
        <StatCard label="Velas descartadas" value={formatNumber(stats.quality.discarded_candles)} />
        <ProgressBar
          value={
            stats.total_candles_downloaded > 0
              ? ((stats.total_candles_inserted + stats.total_candles_updated) /
                  stats.total_candles_downloaded) *
                100
              : 0
          }
          label="Velas persistidas"
        />
      </div>
      {Object.keys(stats.quality.error_kinds).length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/40">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
            Errores de calidad
          </p>
          <ul className="space-y-1 text-sm text-amber-800 dark:text-amber-300">
            {Object.entries(stats.quality.error_kinds).map(([kind, count]) => (
              <li key={kind}>
                {kind}: {formatNumber(count)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {stats.gaps.length > 0 && (
        <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Huecos detectados ({stats.gaps.length})
          </p>
          <ul className="max-h-40 space-y-1 overflow-y-auto text-sm text-slate-600 dark:text-slate-300">
            {stats.gaps.map((gap, i) => (
              <li key={`${gap.symbol}-${gap.timeframe}-${i}`}>
                {gap.symbol} {gap.timeframe}: {new Date(gap.from).toLocaleString()} →{" "}
                {new Date(gap.to).toLocaleString()} ({gap.missing} velas)
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
  danger,
}: {
  label: string;
  value: string;
  accent?: boolean;
  danger?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold ${
          danger ? "text-rose-600 dark:text-rose-400" : accent ? "text-emerald-600 dark:text-emerald-400" : "text-slate-900 dark:text-slate-100"
        }`}
      >
        {value}
      </p>
    </div>
  );
}