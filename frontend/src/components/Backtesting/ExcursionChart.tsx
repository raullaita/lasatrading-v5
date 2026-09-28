import { useMemo } from "react";

import type { ExcursionStats } from "../../types/backtesting";
import { toNumber } from "../../utils/format";

/**
 * Distribucion de una excursion (MAE o MFE) como barras, con los percentiles
 * marcados encima.
 *
 * SVG a mano y no una libreria de charts por dos razones: el eje es un intervalo
 * de porcentaje, no una serie temporal, y lo que hace falta es una silueta con
 * cuatro rayas. lightweight-charts no tiene histogramas; Recharts seria una
 * dependencia entera para pintar doce rectangulos.
 *
 * Las barras vienen del backend ya agrupadas (`buckets`), no se calculan aqui:
 * el histograma se hace una vez por respuesta y no en cada render, y sobre todo
 * asi el grafico y los percentiles que dice el texto son **la misma cuenta**. Si
 * el calculo estuviese en el frontend, dos ruletos distintos acabarian
 * enseñando cosas distintas del mismo run.
 *
 * Las dos lineas discontinuas son el percentil 50 y el 90. El 25 y el 75 se
 * dejan para el texto: marcarlos todos aqui daria una lista de rayas que no se
 * distingue a simple vista, y su lectura es textual de todos modos.
 */

const HEIGHT = 96;
/** Barras con un hueco del 15%: sin separacion parecen un bloque macizo. */
const BAR_GAP = 0.15;

export function ExcursionChart({
  stats,
  color = "indigo",
  signed = false,
}: {
  stats: ExcursionStats;
  /** `indigo` para MFE (a favor), `rose` para MAE (en contra). */
  color?: "indigo" | "rose";
  /** Dibuja el eje desde el cero, para que se vea de que lado cae el MFE. */
  signed?: boolean;
}) {
  const bars = useMemo(
    () =>
      stats.buckets
        .map((bucket) => {
          const lower = toNumber(bucket.lower);
          const upper = toNumber(bucket.upper);
          return {
            lower: lower ?? 0,
            upper: upper ?? 0,
            count: bucket.count,
          };
        })
        .filter((bucket) => Number.isFinite(bucket.lower) && Number.isFinite(bucket.upper)),
    [stats.buckets],
  );

  if (bars.length === 0 || stats.count === 0) {
    return (
      <p className="py-6 text-center text-xs text-slate-400 dark:text-slate-500">
        Sin operaciones en esta población
      </p>
    );
  }

  const valores = bars.flatMap((bucket) => [bucket.lower, bucket.upper]);
  const minimo = Math.min(...valores, signed ? 0 : Infinity);
  const maximo = Math.max(...valores, signed ? 0 : -Infinity);
  const rango = maximo - minimo || 1;
  const tope = Math.max(...bars.map((bucket) => bucket.count));

  const ancho = 100;
  const paso = ancho / bars.length;
  const escala = (valor: number) => (valor - minimo) / rango;
  const colorBarra = color === "rose" ? "fill-rose-400/70" : "fill-indigo-400/70";
  const colorLinea = color === "rose" ? "stroke-rose-500" : "stroke-indigo-500";

  const marcas = [
    { valor: toNumber(stats.p50), etiqueta: "p50" },
    { valor: toNumber(stats.p90), etiqueta: "p90" },
  ].filter((marca) => marca.valor !== null) as { valor: number; etiqueta: string }[];

  const cero = escala(0);

  return (
    <div>
      <svg
        viewBox={`0 0 ${ancho} ${HEIGHT + 14}`}
        preserveAspectRatio="none"
        className="h-28 w-full"
        role="img"
        aria-label={`Distribución de ${stats.count} operaciones`}
      >
        {bars.map((bucket, indice) => {
          const x = indice * paso;
          const altura = (bucket.count / tope) * (HEIGHT - 8);
          return (
            <rect
              key={`${bucket.lower}-${indice}`}
              x={x + paso * BAR_GAP}
              y={HEIGHT - altura}
              width={Math.max(paso * (1 - BAR_GAP * 2), 0.4)}
              height={altura}
              className={colorBarra}
            >
              <title>{`${bucket.lower}% a ${bucket.upper}%: ${bucket.count} operaciones`}</title>
            </rect>
          );
        })}

        {signed && cero > 0 && cero < 1 && (
          <line
            x1={0}
            x2={ancho}
            y1={HEIGHT - cero * HEIGHT}
            y2={HEIGHT - cero * HEIGHT}
            className="stroke-slate-400"
            strokeWidth={0.3}
            strokeDasharray="2 2"
          />
        )}

        {marcas.map((marca) => {
          const x = Math.min(Math.max(escala(marca.valor) * ancho, 0.4), ancho - 0.4);
          return (
            <line
              key={marca.etiqueta}
              x1={x}
              x2={x}
              y1={0}
              y2={HEIGHT}
              className={colorLinea}
              strokeWidth={0.6}
              strokeDasharray="3 2"
            />
          );
        })}
      </svg>

      <div className="mt-1 flex justify-between text-[10px] text-slate-400 dark:text-slate-500">
        <span>{minimo.toFixed(2)}%</span>
        {marcas.map((marca) => (
          <span key={marca.etiqueta}>
            {marca.etiqueta} {marca.valor.toFixed(2)}%
          </span>
        ))}
        <span>{maximo.toFixed(2)}%</span>
      </div>
    </div>
  );
}
