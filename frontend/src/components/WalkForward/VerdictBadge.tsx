import type { WalkForwardVerdict } from "../../types/walkForward";

/**
 * La etiqueta de veredicto, con su color.
 *
 * El color **no** es la informacion: `sostenida` en verde y `descartada` en
 * rojo se leen de un vistazo, pero el texto de por que sigue siendo obligatorio
 * en la pantalla. Una etiqueta de color sin texto convierte un juicio en una
 * sensacion, y un usuario que no distingue el verde del rojo decide lo que sea.
 * Por eso el detalle de la pagina escribe la explicacion entera de la §5.2
 * encima de la tabla, y esta pieza es solo el resumen visual.
 */
const ESTILOS: Record<WalkForwardVerdict, string> = {
  sostenida:
    "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100 border-emerald-400 dark:border-emerald-600",
  prometedora:
    "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100 border-amber-400 dark:border-amber-600",
  descartada:
    "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-300 dark:border-slate-600",
};

const ETIQUETAS: Record<WalkForwardVerdict, string> = {
  sostenida: "Sostenida",
  prometedora: "Prometedora",
  descartada: "Descartada",
};

export function VerdictBadge({ verdict }: { verdict: WalkForwardVerdict }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${ESTILOS[verdict]}`}
    >
      {ETIQUETAS[verdict]}
    </span>
  );
}
