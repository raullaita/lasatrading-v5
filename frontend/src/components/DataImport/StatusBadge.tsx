import type { ImportStatus } from "../../types/dataImport";

const styles: Record<ImportStatus, string> = {
  pending: "bg-slate-100 text-slate-700",
  processing: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-rose-100 text-rose-700",
  cancelled: "bg-amber-100 text-amber-700",
};

const labels: Record<ImportStatus, string> = {
  pending: "Pendiente",
  processing: "Procesando",
  completed: "Completado",
  failed: "Fallido",
  cancelled: "Cancelado",
};

export function StatusBadge({ status }: { status: ImportStatus }) {
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