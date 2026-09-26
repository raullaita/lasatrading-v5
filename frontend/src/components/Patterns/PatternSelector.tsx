import { useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import type { PatternDefinition, PatternParamSpec, PatternSelection } from "../../types/patterns";

/**
 * Selector de patrones con sus parametros, generados desde el catalogo.
 *
 * A diferencia de `IndicatorSelector`, aqui no hay ninguna lista de indicadores
 * ni de etiquetas en el codigo: los diez patrones, sus grupos, sus parametros,
 * sus rangos y sus textos salen de `GET /catalog`. Añadir un patron al backend
 * lo hace aparecer aqui sin tocar este archivo, y cambiar un rango se refleja
 * en los `min`/`max` del input.
 */

const GROUP_LABELS: Record<string, string> = {
  macd_crossover: "Cruce de MACD",
  rsi_extremes: "Salidas de RSI",
  bollinger_breakout: "Ruptura de Bollinger",
  ma_crossover: "Cruce de medias",
  engulfing: "Velas envolventes",
};

/** Valor inicial de un parametro: el default del catalogo. */
function defaultParams(definition: PatternDefinition): Record<string, number> {
  const params: Record<string, number> = {};
  for (const spec of definition.params) {
    params[spec.key] = spec.default;
  }
  return params;
}

/**
 * Recorta un valor al rango del parametro.
 *
 * El backend ya recorta en `resolve_params` al crear el job, asi que esto no es
 * una salvaguarda contra el servidor: es para que el input no muestre `500` en
 * una media movil que solo tiene 200 velas de historia, que es un error
 * visible del usuario y no un rechazo silencioso.
 */
function clamp(value: number, spec: PatternParamSpec): number {
  return Math.min(spec.maximum, Math.max(spec.minimum, value));
}

/** Dedonde sale la direccion para pintar el badge. */
function badgeClasses(direction: string): string {
  return direction === "bullish"
    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
    : "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
}

export function PatternSelector({
  patterns,
  onChange,
  catalog,
  disabled = false,
}: {
  patterns: PatternSelection[];
  onChange: (patterns: PatternSelection[]) => void;
  catalog: PatternDefinition[];
  /** Bloquea toda la interaccion, por ejemplo mientras se envia el job. */
  disabled?: boolean;
}) {
  // Solo se despliega un grupo a la vez. Con diez patrones en pantalla todas
  // las abiertas, los inputs de parametros serian un muro.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => {
    const map = new Map<string, PatternDefinition[]>();
    for (const definition of catalog) {
      const list = map.get(definition.group) ?? [];
      list.push(definition);
      map.set(definition.group, list);
    }
    // Todos los grupos empiezan plegados salvo el primero: en una sesion
    // tipica se escanea un patron.
    return Array.from(map.entries());
  }, [catalog]);

  const toggle = (definition: PatternDefinition) => {
    if (disabled) return;
    const selected = patterns.some((p) => p.code === definition.code);
    if (selected) {
      onChange(patterns.filter((p) => p.code !== definition.code));
    } else {
      onChange([...patterns, { code: definition.code, params: defaultParams(definition) }]);
    }
  };

  const updateParam = (code: string, key: string, raw: string, spec: PatternParamSpec) => {
    const parsed = parseFloat(raw);
    if (Number.isNaN(parsed)) return;
    onChange(
      patterns.map((p) =>
        p.code === code ? { ...p, params: { ...p.params, [key]: clamp(parsed, spec) } } : p,
      ),
    );
  };

  const isExpanded = (code: string) => expanded[code] ?? false;

  if (catalog.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-4 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Cargando catálogo de patrones…
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {groups.map(([group, definitions], groupIdx) => {
        const isOpen = openGroups[group] ?? groupIdx === 0;
        const selectedCount = definitions.filter((d) =>
          patterns.some((p) => p.code === d.code),
        ).length;

        return (
          <div
            key={group}
            className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800"
          >
            <button
              type="button"
              disabled={disabled}
              onClick={() => setOpenGroups((prev) => ({ ...prev, [group]: !isOpen }))}
              className="flex w-full items-center gap-2 bg-slate-50 px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              {isOpen ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0" />
              )}
              <span className="flex-1">{GROUP_LABELS[group] ?? group}</span>
              {selectedCount > 0 && (
                <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">
                  {selectedCount}
                </span>
              )}
            </button>

            {isOpen && (
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {definitions.map((definition) => {
                  const selected = patterns.find((p) => p.code === definition.code);
                  const showParams = selected !== undefined && isExpanded(definition.code);

                  return (
                    <div key={definition.code} className="px-3 py-2">
                      <div className="flex items-start gap-2">
                        <input
                          id={`pattern-${definition.code}`}
                          type="checkbox"
                          checked={selected !== undefined}
                          disabled={disabled}
                          onChange={() => toggle(definition)}
                          className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-950"
                        />
                        <label
                          htmlFor={`pattern-${definition.code}`}
                          className="min-w-0 flex-1 cursor-pointer"
                        >
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="text-xs font-semibold text-slate-800 dark:text-slate-100">
                              {definition.short_label}
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${badgeClasses(
                                definition.direction,
                              )}`}
                            >
                              {definition.direction === "bullish" ? "alcista" : "bajista"}
                            </span>
                          </span>
                          <span className="mt-0.5 block text-[11px] leading-snug text-slate-500 dark:text-slate-400">
                            {definition.description}
                          </span>
                        </label>
                      </div>

                      {selected !== undefined && definition.params.length > 0 && (
                        <div className="ml-6 mt-2">
                          {showParams ? (
                            <div className="flex flex-wrap gap-3 rounded-md bg-slate-50 p-2 dark:bg-slate-800/50">
                              {definition.params.map((spec) => (
                                <label
                                  key={spec.key}
                                  className="text-[11px] text-slate-600 dark:text-slate-300"
                                  title={spec.help}
                                >
                                  <span className="block">{spec.label}</span>
                                  <input
                                    type="number"
                                    disabled={disabled}
                                    value={selected.params[spec.key] ?? spec.default}
                                    min={spec.minimum}
                                    max={spec.maximum}
                                    step={spec.step}
                                    onChange={(e) =>
                                      updateParam(definition.code, spec.key, e.target.value, spec)
                                    }
                                    className="mt-0.5 w-20 rounded border border-slate-300 px-1.5 py-0.5 text-xs focus:border-indigo-500 focus:outline-none disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                                  />
                                  <span className="mt-0.5 block text-[10px] text-slate-400 dark:text-slate-500">
                                    {spec.minimum}–{spec.maximum}
                                  </span>
                                </label>
                              ))}
                            </div>
                          ) : (
                            <button
                              type="button"
                              disabled={disabled}
                              onClick={() =>
                                setExpanded((prev) => ({
                                  ...prev,
                                  [definition.code]: true,
                                }))
                              }
                              className="text-[11px] text-indigo-600 hover:underline disabled:opacity-50 dark:text-indigo-400"
                            >
                              Ajustar parámetros (
                              {definition.params
                                .map((s) => selected.params[s.key] ?? s.default)
                                .join(", ")}
                              )
                            </button>
                          )}
                        </div>
                      )}

                      {selected !== undefined && (
                        <div className="ml-6 mt-2 flex flex-wrap gap-1">
                          {definition.required_features.map((feature) => (
                            <span
                              key={feature}
                              className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                            >
                              {feature}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {patterns.length === 0 && (
        <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          Selecciona al menos un patrón. El backend rechaza la petición con 422 si la lista llega
          vacía.
        </p>
      )}
    </div>
  );
}
