import type { ImportStatus } from "../../types/dataImport";
import type { FeatureJobStatus } from "../../types/features";
import type { PatternScanJobStatus } from "../../types/patterns";

/**
 * Badge de estado compartido por los módulos que llevan un job con estados.
 *
 * Antes de existir este archivo había una copia en `Features`, otra en
 * `Patterns` y otra en `DataImport`, idénticas byte a byte salvo por el tipo
 * que anotaba `Record`. Un solo componente evita que un estado nuevo se
 * pinte en dos de los tres sitios y no en el tercero.
 *
 * Los tres módulos declaran hoy el mismo union de cinco estados. Si alguno
 * divergiera, este `Record` dejaría de cubrir el tipo y el error sale aquí,
 * que es justo lo que se busca: que la duplicación salga a la luz en el
 * momento de romperla y no tres meses después en un badge mal pintado.
 */
export type JobStatus = FeatureJobStatus | ImportStatus | PatternScanJobStatus;

const styles: Record<JobStatus, string> = {
  pending: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  processing: "bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  failed: "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  cancelled: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
};

const labels: Record<JobStatus, string> = {
  pending: "Pendiente",
  processing: "Procesando",
  completed: "Completado",
  failed: "Fallido",
  cancelled: "Cancelado",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${styles[status]}`}
    >
      {status === "processing" && (
        <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
      )}
      {labels[status]}
    </span>
  );
}
