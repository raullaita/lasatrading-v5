import type { BacktestBenchmark, BacktestRunResponse } from "../../types/backtesting";
import { formatDelta, formatPercent, toNumber } from "../../utils/format";

/**
 * La fila que hace legibles todas las demas: estrategia contra mercado.
 *
 * Sin esto, un -3,02% y un +37,70% son dos resultados y no se sabe si ninguno
 * de los dos era bueno. Con esto, los dos son el mismo resultado —perder dinero
 * mientras el mercado subia— y por tanto el mismo veredicto.
 *
 * El orden de las cifras es intencionado y va contra la costumbre: primero
 * **el mercado**, luego la estrategia, y despues la diferencia. Almostrar la
 * estrategia primero, el ojo se queda en ella y la comparacion pasa
 * desapercibida; el orden inverso hace que la diferencia sea lo que se lee.
 *
 * El veredicto no se deduce de la diferencia sino de las dos a la vez, porque
 * superar al mercado no es sinonimo de ganar dinero:
 *
 * * Supera al mercado y gana: lo unico que hay que mirar es cuanto.
 * * Supera al mercado y pierde: el mercado cae mas de lo que cae la estrategia,
 *   que es cambiar a modo defensivo. No es ganar dinero.
 * * No supera al mercado: la estrategia no esta alpha, es beta con comisiones.
 */
export function BenchmarkRow({
  run,
  benchmark,
}: {
  run: BacktestRunResponse;
  benchmark: BacktestBenchmark | null;
}) {
  const mercado = toNumber(benchmark?.total_return_pct);
  const estrategia = toNumber(run.total_return_pct);

  if (!benchmark || benchmark.candles === 0 || mercado === null || estrategia === null) {
    return (
      <p className="rounded-xl border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Sin benchmark de mercado para este run: no hay velas en el rango del escaneo con las que
        comparar. Un resultado sin referencia no dice si la estrategia funciona.
      </p>
    );
  }

  const diferencia = estrategia - mercado;
  const drawdownEstrategia = toNumber(run.max_drawdown_pct);
  const drawdownMercado = toNumber(benchmark.max_drawdown_pct);
  const bateAlMercado = diferencia > 0;

  const veredicto = !bateAlMercado
    ? "La estrategia no supera al mercado: esto es lo que hacia el activo, con comisiones por medio y saliendo antes de tiempo."
    : estrategia > 0
      ? "Supera al mercado y gana dinero. Lo unico que queda por mirar es cuanto, y si aguanta fuera de este rango."
      : "Supera al mercado pero pierde dinero: el mercado cae mas de lo que cae la estrategia. Es un cambio a defensivo, no una estrategia ganadora.";

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/50">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">Contra el mercado</h3>
        <span className="text-xs text-slate-400 dark:text-slate-500">
          {benchmark.candles.toLocaleString("es-ES")} velas · {formatPercent(benchmark.entry_price)}{" "}
          → {formatPercent(benchmark.final_price)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Celda
          etiqueta="Mercado (sin operar)"
          valor={formatPercent(mercado)}
          tono={mercado >= 0 ? "positivo" : "negativo"}
        />
        <Celda
          etiqueta="Estrategia"
          valor={formatPercent(estrategia)}
          tono={estrategia >= 0 ? "positivo" : "negativo"}
        />
        <Celda
          etiqueta="Diferencia"
          valor={formatDelta(diferencia)}
          tono={bateAlMercado ? "positivo" : "negativo"}
        />
        <Celda
          etiqueta="Drawdown"
          valor={
            drawdownEstrategia === null
              ? "—"
              : `${formatPercent(drawdownEstrategia)} vs ${formatPercent(drawdownMercado)}`
          }
        />
      </div>

      <p className="mt-3 text-xs leading-5 text-slate-600 dark:text-slate-300">{veredicto}</p>
    </div>
  );
}

function Celda({
  etiqueta,
  valor,
  tono = "neutral",
}: {
  etiqueta: string;
  valor: string;
  tono?: "neutral" | "positivo" | "negativo";
}) {
  const color =
    tono === "positivo"
      ? "text-emerald-600 dark:text-emerald-400"
      : tono === "negativo"
        ? "text-rose-600 dark:text-rose-400"
        : "text-slate-900 dark:text-slate-100";
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">
        {etiqueta}
      </p>
      <p className={`text-sm font-semibold ${color}`}>{valor}</p>
    </div>
  );
}
