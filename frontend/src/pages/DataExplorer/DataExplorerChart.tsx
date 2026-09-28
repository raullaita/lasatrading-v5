import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Loader2, RefreshCw, TriangleAlert } from "lucide-react";

import { UnifiedChart } from "../../components/charts/UnifiedChart";
import { toChartRows } from "../../components/charts/chartData";
import { getIndicatorAvailability } from "../../services/featuresApi";
import { getDataSummary } from "../../services/dataApi";
import { getChartData, getPatternScans } from "../../services/patternsApi";
import type { ChartData, IndicatorAvailability } from "../../types/chart";
import { formatDateEs } from "../../utils/format";

/**
 * Explorador de velas. Es la Fase 1 del roadmap y no necesita ningun job previo:
 * se elige símbolo, timeframe y rango, y sale el grafico.
 *
 * **Todo el estado vive en la query string**, y no por capricho: una vista de un
 * tramo concreto del mercado con unos indicadores concretos es justo lo que se
 * quiere poder mandar por URL. "Mira el gráfico de BTCUSDT en 2022 con el
 * MACD" deja de ser una sesion de ocho clics y pasa a ser un enlace. Por eso no
 * hay estado de rango ni de indicadores en `useState`: sale de la URL y se
 * escribe en la URL.
 *
 * Los indicadores que se ofrecen son **los que existen en la base**, con su
 * cobertura real, y el selector marca los que no cubren el rango elegido. El
 * grafico no calcula nada: un valor en pantalla sin un job que lo haya producido
 * rompe la trazabilidad desde el primer eslabón, que es lo que luego sostiene la
 * calibración, la validación cruzada y las alertas.
 */
const PRESETS: { label: string; days: number | "all" }[] = [
  { label: "7 días", days: 7 },
  { label: "30 días", days: 30 },
  { label: "90 días", days: 90 },
  { label: "6 meses", days: 182 },
  { label: "1 año", days: 365 },
  { label: "Todo", days: "all" },
];

const DEFAULT_MAX_POINTS = 1500;

export default function DataExplorer() {
  const [params, setParams] = useSearchParams();

  const symbol = params.get("symbol") ?? "";
  const timeframe = params.get("timeframe") ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const scan = params.get("scan") ?? "";
  const features = useMemo(
    () => (params.get("features") ?? "").split(",").filter(Boolean),
    [params],
  );

  const [grupos, setGrupos] = useState<
    {
      symbol: string;
      timeframe: string;
      first_timestamp: string;
      last_timestamp: string;
      total_candles: number;
    }[]
  >([]);
  const [disponibles, setDisponibles] = useState<IndicatorAvailability[]>([]);
  const [escaneos, setEscaneos] = useState<{ id: string; label: string }[]>([]);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const actualizar = useCallback(
    (cambios: Record<string, string | null>) => {
      const siguiente = new URLSearchParams(params);
      for (const [clave, valor] of Object.entries(cambios)) {
        if (valor === null || valor === "") siguiente.delete(clave);
        else siguiente.set(clave, valor);
      }
      setParams(siguiente, { replace: true });
    },
    [params, setParams],
  );

  // Inventario de pares con velas, para el selector y para acotar el rango.
  useEffect(() => {
    void getDataSummary()
      .then((data) => setGrupos(data.groups))
      .catch(() => setGrupos([]));
  }, []);

  // Indicadores ya calculados para el par elegido.
  useEffect(() => {
    if (!symbol || !timeframe) {
      setDisponibles([]);
      return;
    }
    void getIndicatorAvailability(symbol, timeframe)
      .then((data) => setDisponibles(data.indicators))
      .catch(() => setDisponibles([]));
  }, [symbol, timeframe]);

  // Escaneos de ese par, para marcar detecciones si se elige uno.
  useEffect(() => {
    if (!symbol || !timeframe) return;
    void getPatternScans({ symbol, timeframe, page_size: 100 })
      .then((data) =>
        setEscaneos(
          data.jobs
            .filter((job) => job.status === "completed")
            .map((job) => ({
              id: job.id,
              label: `${formatDateEs(job.date_from)} → ${formatDateEs(job.date_to)} · ${job.processed_candles} velas`,
            })),
        ),
      )
      .catch(() => setEscaneos([]));
  }, [symbol, timeframe]);

  // El grafico. Solo se pide cuando hay simbolo, timeframe y rango completos.
  useEffect(() => {
    if (!symbol || !timeframe || !from || !to) {
      setChart(null);
      return;
    }
    let vigente = true;
    setCargando(true);
    setError(null);
    void getChartData({
      symbol,
      timeframe,
      date_from: from,
      date_to: to,
      features: features.join(","),
      scan: scan || undefined,
      max_points: DEFAULT_MAX_POINTS,
    })
      .then((data) => {
        if (vigente) setChart(data);
      })
      .catch(() => {
        if (vigente) {
          setChart(null);
          setError("No se pudo cargar el gráfico.");
        }
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [symbol, timeframe, from, to, features, scan]);

  const parElegido = grupos.find((g) => g.symbol === symbol && g.timeframe === timeframe);
  const filas = useMemo(() => (chart ? toChartRows(chart) : []), [chart]);

  /** Indicadores cuya cobertura no llega al rango elegido. */
  const ausentes = useMemo(() => {
    if (!from || !to) return [];
    return disponibles.filter((ind) => ind.date_from > from || ind.date_to < to);
  }, [disponibles, from, to]);

  const alternarIndicador = (nombre: string) => {
    const siguiente = features.includes(nombre)
      ? features.filter((f) => f !== nombre)
      : [...features, nombre];
    actualizar({ features: siguiente.join(",") });
  };

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-7xl space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
            Explorador de datos
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Las velas son las que hay en la base. Los indicadores también: aquí no se calcula nada.
          </p>
        </div>

        <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-4 dark:border-slate-800 dark:bg-slate-900">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">
              Símbolo
            </span>
            <select
              value={symbol}
              onChange={(e) => {
                const siguiente =
                  grupos.find((g) => g.symbol === e.target.value && g.timeframe === timeframe) ??
                  grupos.find((g) => g.symbol === e.target.value);
                actualizar({
                  symbol: e.target.value || null,
                  timeframe: siguiente?.timeframe ?? null,
                  from: null,
                  to: null,
                  scan: null,
                });
              }}
              className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="">Selecciona un símbolo</option>
              {Array.from(new Set(grupos.map((g) => g.symbol))).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">
              Timeframe
            </span>
            <select
              value={timeframe}
              onChange={(e) =>
                actualizar({ timeframe: e.target.value || null, from: null, to: null })
              }
              className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="">—</option>
              {grupos
                .filter((g) => g.symbol === symbol)
                .map((g) => (
                  <option key={g.timeframe} value={g.timeframe}>
                    {g.timeframe}
                  </option>
                ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">
              Desde
            </span>
            <input
              type="date"
              value={from.slice(0, 10)}
              onChange={(e) =>
                actualizar({ from: e.target.value ? `${e.target.value}T00:00:00Z` : null })
              }
              className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">
              Hasta
            </span>
            <input
              type="date"
              value={to.slice(0, 10)}
              onChange={(e) =>
                actualizar({ to: e.target.value ? `${e.target.value}T23:59:59Z` : null })
              }
              className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>

          <div className="flex flex-wrap items-center gap-2 lg:col-span-4">
            {PRESETS.map((preset) => {
              const activo =
                preset.days === "all"
                  ? parElegido && from === parElegido.first_timestamp.slice(0, 10) + "T00:00:00Z"
                  : false;
              return (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => {
                    if (!parElegido) return;
                    if (preset.days === "all") {
                      actualizar({
                        from: parElegido.first_timestamp,
                        to: parElegido.last_timestamp,
                      });
                      return;
                    }
                    const fin = new Date(parElegido.last_timestamp);
                    const inicio = new Date(fin.getTime() - preset.days * 86400000);
                    actualizar({
                      from: inicio.toISOString(),
                      to: parElegido.last_timestamp,
                    });
                  }}
                  className={`rounded-full border px-2.5 py-1 text-xs ${
                    activo
                      ? "border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-300"
                      : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
            {parElegido && (
              <span className="text-xs text-slate-400">
                {parElegido.total_candles.toLocaleString("es-ES")} velas disponibles
              </span>
            )}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <aside className="space-y-4">
            <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <h2 className="mb-2 text-sm font-bold text-slate-900 dark:text-slate-100">
                Indicadores superpuestos
              </h2>
              {!symbol || !timeframe ? (
                <p className="text-xs text-slate-400">Elige símbolo y timeframe.</p>
              ) : disponibles.length === 0 ? (
                <p className="text-xs text-slate-400">
                  Este par no tiene ningún indicador calculado. Calcúlalos en «Indicadores».
                </p>
              ) : (
                <ul className="space-y-1">
                  {disponibles.map((ind) => {
                    const marcado = features.includes(ind.name);
                    const cubre = ausentes.some((a) => a.name === ind.name);
                    return (
                      <li key={ind.name}>
                        <label
                          className={`flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm ${
                            marcado
                              ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200"
                              : "text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={marcado}
                            onChange={() => alternarIndicador(ind.name)}
                            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className="font-mono text-xs">{ind.name}</span>
                          {cubre && (
                            <span
                              title={`Solo tiene datos de ${formatDateEs(ind.date_from)} a ${formatDateEs(ind.date_to)}`}
                              className="ml-auto text-amber-500"
                            >
                              <TriangleAlert className="h-3.5 w-3.5" />
                            </span>
                          )}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              {ausentes.length > 0 && (
                <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  Con el aviso hay {ausentes.length} indicador(es) calculados pero fuera del rango
                  elegido. El backend lo avisa en <code>missing_indicators</code> cuando se piden.
                </p>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <h2 className="mb-2 text-sm font-bold text-slate-900 dark:text-slate-100">
                Detecciones de un escaneo
              </h2>
              <select
                value={scan}
                onChange={(e) => actualizar({ scan: e.target.value || null })}
                className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              >
                <option value="">Sin marcadores</option>
                {escaneos.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.label}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                Sin escaneo no hay flechas: no se puede marcar lo que no se ha detectado.
              </p>
            </div>
          </aside>

          <div className="space-y-3">
            {error && (
              <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
                {error}
              </p>
            )}

            {symbol && timeframe && !from && (
              <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                Elige un rango para ver el gráfico. Puedes usar los atajos de arriba.
              </p>
            )}

            {symbol && timeframe && from && to && (
              <>
                {chart && (
                  <UnifiedChart
                    rows={filas}
                    markers={chart.markers}
                    title={`${symbol} · ${timeframe}`}
                    subtitle={
                      `${formatDateEs(from)} → ${formatDateEs(to)}` +
                      (chart.sampled
                        ? ` · mostrando ${chart.returned.toLocaleString("es-ES")} de ${chart.total_points.toLocaleString("es-ES")} velas (1 de cada ${chart.step})`
                        : ` · ${chart.returned.toLocaleString("es-ES")} velas`)
                    }
                  />
                )}

                {chart && chart.missing_indicators.length > 0 && (
                  <p className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                    <TriangleAlert className="h-4 w-4 shrink-0" />
                    <span>
                      Sin datos en este rango: {chart.missing_indicators.join(", ")}. Se han pedido
                      de forma explícita y no tienen ni un punto entre {formatDateEs(from)} y{" "}
                      {formatDateEs(to)}.
                    </span>
                    <Link to="/features/new" className="font-medium underline">
                      Calcularlos
                    </Link>
                  </p>
                )}

                {cargando && (
                  <p className="flex items-center gap-2 text-sm text-slate-500">
                    <Loader2 className="h-4 w-4 animate-spin" /> Cargando velas…
                  </p>
                )}
              </>
            )}
          </div>
        </section>

        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <RefreshCw className="h-3.5 w-3.5" />
          La URL lleva símbolo, timeframe, rango, indicadores y escaneo: se puede compartir la vista
          tal cual.
        </p>
      </div>
    </main>
  );
}
