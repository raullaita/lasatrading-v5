import type { FeatureJobResponse } from "../../types/features";
import { ProgressBar } from "./ProgressBar";

const formatNumber = (n: number) => n.toLocaleString("es");

export function StatsPanel({ job }: { job: FeatureJobResponse }) {
  const restantes = Math.max(0, job.total_candles - job.processed_candles);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Velas totales" value={formatNumber(job.total_candles)} />
        <StatCard label="Procesadas" value={formatNumber(job.processed_candles)} accent />
        <StatCard label="Restantes" value={formatNumber(restantes)} />
        <StatCard label="Indicadores" value={`${job.indicators_config.length}`} />
      </div>
      <ProgressBar
        current={job.processed_candles}
        total={job.total_candles}
        label="Cálculo completado"
      />
      {job.status === "failed" && job.error_message && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/40">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
            Error del cálculo
          </p>
          <p className="text-sm text-amber-800 dark:text-amber-300">{job.error_message}</p>
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
          danger
            ? "text-rose-600 dark:text-rose-400"
            : accent
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-slate-900 dark:text-slate-100"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
