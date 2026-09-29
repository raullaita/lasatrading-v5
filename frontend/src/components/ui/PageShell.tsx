import type { ReactNode } from "react";

/**
 * El esqueleto de página que usan todas las listas del proyecto.
 *
 * Existe porque las clases estaban **repetidas** en cada pantalla, y cuando
 * alguien escribe una pantalla nueva con `rounded border` en vez de
 * `rounded-xl` y `font-semibold` en vez de `font-bold` no se nota en el código
 * ni en la revisión: se nota al abrir la aplicación, que parece un conjunto de
 * módulos pegados en vez de un producto. Es el mismo motivo por el que existe
 * `components/ui/StatusBadge.tsx`.
 *
 * Las clases concretas salen de `BacktestList` y `PatternList`, que son las dos
 * pantallas que ya tenían el estándar. Si algún día se cambia el estándar, se
 * cambia aquí y en las dos, y no en veinte sitios.
 *
 * `wide` existe para el Centro de Investigación Visual, y solo por una razón:
 * el gráfico **es** la pantalla, y a 1.152 px las velas se estreitan hasta
 * perder la forma. Todos los demás usos van por `max-w-6xl`.
 */
export function PageShell({
  children,
  wide = false,
}: {
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className={wide ? "mx-auto max-w-7xl" : "mx-auto max-w-6xl"}>{children}</div>
    </main>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-center justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {subtitle}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** La barra de filtros. `items-end` alinea los campos por su base, no por su centro. */
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      {children}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}

/** Los `focus:border-indigo-500` no son adorno: son lo que se ve al tabular. */
export const inputClass =
  "rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

export const primaryButtonClass =
  "inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50";

export const secondaryButtonClass =
  "inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800";

export const dangerButtonClass =
  "inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:bg-slate-900 dark:hover:bg-rose-950/50";

export const errorClass =
  "mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400";

export const cardClass = "rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900";

export const tableClass = "overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900";

/**
 * La cabecera de tabla.
 *
 * El `text-xs uppercase tracking-wide` y el `border-b` son lo que separan una
 * tabla de un bloque de texto con lineas. Sin ellos la tabla se lee como si
 * flotara.
 */
export const tableHeadClass =
  "border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400";

export const tableHeadCellClass = "px-4 py-2.5";

export const tableBodyClass = "divide-y divide-slate-100 dark:divide-slate-800";

export const tableCellClass = "px-4 py-2.5";

/** El estado vacío va **dentro** de la tabla, no fuera: una tabla sin filas con
 *  borde y una tabla con un mensaje centrado se leen como la misma cosa. */
export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td
        colSpan={colSpan}
        className="px-4 py-10 text-center text-slate-500 dark:text-slate-400"
      >
        {children}
      </td>
    </tr>
  );
}
