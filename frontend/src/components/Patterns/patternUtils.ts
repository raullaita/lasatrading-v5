import type { PatternDefinition, PatternSelection } from "../../types/patterns";

/**
 * Utilidades compartidas por los componentes de patrones.
 *
 * Viven aquí y no en `PatternSelector.tsx` porque eslint
 * (`react-refresh/only-export-components`) avisa cuando un archivo de componente
 * exporta algo más que componentes: el resultado es que el HMR deja de
 * funcionar para ese archivo en desarrollo. Es una función pura, no un
 * componente, así que no le corresponde estar ahí.
 */

/**
 * Features que faltan para poder ejecutar los patrones seleccionados.
 *
 * Se cruza `PatternDefinition.required_features` del catálogo contra los
 * `indicators` que devuelve `getAvailableData()`. Existe para avisar *antes* de
 * encolar: sin `EMA_50`, un `MA_CROSS_BULLISH` está destined a fallar con
 * `MissingFeaturesError` en el worker, y descubrirlo leyendo los logs del job
 * es una forma mala de enterarse de que el selector de datos no está completo.
 *
 * Devuelve la lista ordenada y sin duplicados, lista para pintar como aviso.
 */
export function missingFeatures(
  patterns: PatternSelection[],
  catalog: PatternDefinition[],
  availableIndicators: string[],
): string[] {
  const byCode = new Map(catalog.map((d) => [d.code, d]));
  const have = new Set(availableIndicators);
  const missing = new Set<string>();

  for (const selection of patterns) {
    const definition = byCode.get(selection.code);
    if (!definition) continue;
    for (const feature of definition.required_features) {
      if (!have.has(feature)) missing.add(feature);
    }
  }

  return Array.from(missing).sort();
}
