import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

export function SortableTh({
  label,
  sortKey,
  sortBy,
  sortOrder,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: string;
  sortBy: string;
  sortOrder: "asc" | "desc";
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sortBy === sortKey;
  return (
    <th className={`px-4 py-2.5 ${className}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 uppercase tracking-wide ${
          className === "text-right" ? "justify-end" : ""
        } ${
          active
            ? "text-slate-900 dark:text-slate-100"
            : "hover:text-slate-900 dark:hover:text-slate-100"
        }`}
      >
        {label}
        {active ? (
          sortOrder === "asc" ? (
            <ArrowUp className="h-3.5 w-3.5" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5" />
          )
        ) : (
          <ChevronsUpDown className="h-3.5 w-3.5 opacity-40" />
        )}
      </button>
    </th>
  );
}