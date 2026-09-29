import type { AlertPatternCoverage, AlertValidationStatus } from "../../types/alerts";

/**
 * El estado de validación de una configuración, y **por qué**.
 *
 * Este componente es el que carga con la decisión de diseño más importante del
 * módulo. El backend ya no rechaza reglas por tener un veredicto malo —con los
 * datos actuales un filtro duro haría el sistema inservible—, así que **la
 * seguridad se ha mudado del rechazo a la visibilidad**: si el usuario no puede
 * ver de un vistazo que una configuración está descartada, el sistema le está
 * distribuyendo señales que el optimizador ya probó que pierden.
 *
 * Por eso el icono va primero y en color, y el texto va debajo y siempre. Un
 * color sin texto obliga a distinguir tonos, y quien no los distingue decide lo
 * que sea.
 */

const ICONO: Record<AlertValidationStatus, string> = {
  sostenida: "✅",
  prometedora: "🟡",
  descartada: "🔴",
  sin_evaluar: "⚪",
};

const ETIQUETA: Record<AlertValidationStatus, string> = {
  sostenida: "Validada",
  prometedora: "Sin evidencia fuerte",
  descartada: "Descartada",
  sin_evaluar: "Sin respaldo",
};

const CLASE: Record<AlertValidationStatus, string> = {
  sostenida: "bg-emerald-50 border-emerald-300 dark:bg-emerald-950/40 dark:border-emerald-700",
  prometedora: "bg-amber-50 border-amber-300 dark:bg-amber-950/40 dark:border-amber-700",
  descartada: "bg-rose-50 border-rose-300 dark:bg-rose-950/40 dark:border-rose-700",
  sin_evaluar: "bg-slate-50 border-slate-300 dark:bg-slate-900 dark:border-slate-600",
};

/** La línea que explica el estado, y que no es un adorno. */
const EXPLICACION: Record<AlertValidationStatus, string> = {
  sostenida: "El intervalo de confianza excluye el cero y se evaluó en tres regímenes o más.",
  prometedora:
    "Pasa las guardas, pero el intervalo incluye el cero: el resultado es compatible con haber sido azar.",
  descartada:
    "El optimizador descartó esta configuración. La alerta se envía igualmente porque la decisión es tuya, no de la herramienta.",
  sin_evaluar: "Ningún backtest evaluó esta configuración. Es una intuición, no un resultado.",
};

export function ValidationBadge({
  status,
  note,
  compact = false,
}: {
  status: AlertValidationStatus;
  note?: string | null;
  compact?: boolean;
}) {
  return (
    <div className={`rounded border px-2 py-1.5 ${CLASE[status]}`}>
      <div className="flex items-center gap-1.5">
        <span aria-hidden="true">{ICONO[status]}</span>
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {ETIQUETA[status]}
        </span>
      </div>
      <p className="mt-1 text-xs leading-snug text-slate-600 dark:text-slate-300">
        {note || EXPLICACION[status]}
      </p>
      {compact ? null : (
        <p className="mt-1 text-[11px] leading-snug text-slate-500 dark:text-slate-400">
          {EXPLICACION[status]}
        </p>
      )}
    </div>
  );
}

/**
 * La cobertura del patrón, que va **aparte** del veredicto.
 *
 * Un informe sobre un escaneo de cuatro patrones puede salir «validada» y no
 * haber mirado jamás el patrón del que alerta la regla. Si eso se colgara del
 * mismo badge, el usuario leería «validada» y no sabría que los niveles nunca se
 * simularon con ese patrón, que es justo el dato que convierte una alerta en una
 * intuición disfrazada de resultado.
 */
const COBERTURA: Record<AlertPatternCoverage, { icono: string; texto: string }> = {
  cubierto: { icono: "✅", texto: "El informe evaluó este patrón" },
  fuera_de_filtro: {
    icono: "⚠️",
    texto: "El informe NO evaluó este patrón: estos niveles nunca se simularon con él",
  },
  sin_informe: { icono: "ℹ️", texto: "Sin informe de respaldo" },
};

export function CoverageBadge({ coverage }: { coverage: AlertPatternCoverage }) {
  const info = COBERTURA[coverage];
  const tono =
    coverage === "fuera_de_filtro"
      ? "text-amber-700 dark:text-amber-300"
      : coverage === "cubierto"
        ? "text-slate-500 dark:text-slate-400"
        : "text-slate-400 dark:text-slate-500";
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${tono}`} title={info.texto}>
      <span aria-hidden="true">{info.icono}</span>
      {info.texto}
    </span>
  );
}
