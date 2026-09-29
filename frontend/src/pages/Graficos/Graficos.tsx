import { useCallback, useEffect, useMemo, useState } from "react";

import { Link, useSearchParams } from "react-router-dom";

import { Crosshair, Loader2, RefreshCw, TriangleAlert } from "lucide-react";

import { UnifiedChart } from "../../components/charts/UnifiedChart";
import { toChartRows } from "../../components/charts/chartData";
import {
  Field,
  PageHeader,
  PageShell,
  cardClass,
  errorClass,
  inputClass,
} from "../../components/ui/PageShell";
import { getIndicatorAvailability } from "../../services/featuresApi";
import { getDataSummary } from "../../services/dataApi";
import { getChartData, getPatternScans } from "../../services/patternsApi";
import type { ChartData, IndicatorAvailability } from "../../types/chart";
import type { PatternChartMarker } from "../../types/patterns";
import { formatDateEs, formatDateTimeEs } from "../../utils/format";

/**
 * Centro de Investigacion Visual.
 *
 * La pantalla se organiza en tres bloques y en ese orden, porque es el orden en
 * que se hacen las preguntas:
 *
 * **A · Qué miro.** Simbolo, timeframe, rango e indicadores. Es arriba y en una
 * fila porque es lo que se cambia entre vista y vista, y porque quien llega con
 * un enlace ya trae los cinco en la URL y no deberia tener que tocarlos.
 *
 * **B · El grafico.** Protagonista, ancho y alto. Sin panel lateral que le
 * robe ancho: el ancho es la dimension que mas limita leer una vela.
 *
 * **C · Las detecciones.** Debajo, en texto, porque una flecha de 6 px sobre una
 * vela no se puede leer. Al pinchar una, el grafico se centra en ella. Y estan
 * en texto **y** con la flecha, no en vez de: la flecha sitúa en el grafico y la
 * fila da el patron, la fecha y la direccion.
 *
 * **Todo el estado vive en la query string**, y no por capricho: una vista de un
 * tramo concreto del mercado con unos indicadores concretos es justo lo que se
 * quiere poder mandar por URL. "Mira el grafico de BTCUSDT en 2022 con el MACD"
 * deja de ser una sesion de ocho clics y pasa a ser un enlace. Por eso no hay
 * estado de rango ni de indicadores en `useState`: sale de la URL y se escribe
 * en la URL. La unica excepcion es la deteccion enfocada, que es de la sesion
 * y no merece un parametro mas en un enlace que se manda a alguien.
 *
 * El grafico no calcula nada: una vela sin OHLCV no sale. Un valor en pantalla
 * sin un job que lo haya producido rompe la trazabilidad desde el primer
 * eslabon, que es lo que luego sostiene la calibracion, la validacion cruzada y
 * las alertas.
 */

/** Atajos de rango. Los tres que se usan a diario, mas «todo» para buscar. */
const RANGOS: { etiqueta: string; dias: number | "all" }[] = [
  { etiqueta: "1M", dias: 30 },
  { etiqueta: "3M", dias: 91 },
  { etiqueta: "1A", dias: 365 },
  { etiqueta: "Todo", dias: "all" },
];

/** Cuantas detecciones se pintan antes de resumir el resto. */
const MAX_DETECCIONES = 60;

const DEFAULT_MAX_POINTS = 1500;

/** Alto del grafico. Mas que el de las otras pantallas porque aqui no hay tabla debajo. */
const ALTO_GRAFICO = 520;

export default function Graficos() {
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

  /** La vela enfocada. A proposito fuera de la URL: es de la sesion. */
  const [foco, setFoco] = useState<string | null>(null);

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

  /** Cambiar de par o de rango invalida el foco: la vela enfocada puede no existir ya. */
  useEffect(() => {
    setFoco(null);
  }, [symbol, timeframe, from, to, scan]);

  const parElegido = grupos.find((g) => g.symbol === symbol && g.timeframe === timeframe);
  const filas = useMemo(() => (chart ? toChartRows(chart) : []), [chart]);

  /** Indicadores cuya cobertura no llega al rango elegido. */
  const ausentes = useMemo(() => {
    if (!from || !to) return [];
    return disponibles.filter((ind) => ind.date_from > from || ind.date_to < to);
  }, [disponibles, from, to]);

  /** Las detecciones que caen dentro de las velas pintadas.
   *
   *  El backend devuelve los markers del rango completo, no solo los del tramo
   *  muestreado, asi que una deteccion fuera de lo pintado no se puede ni
   *  localizar. Enseñar la lista entera y dejar que la flecha este en otro
   *  sitio es peor que no enseñarla: es una lista que miente.
   */
  const detecciones = useMemo(() => {
    if (!chart) return [] as PatternChartMarker[];
    const primero = chart.candles[0]?.timestamp;
    const ultimo = chart.candles[chart.candles.length - 1]?.timestamp;
    if (!primero || !ultimo) return [];
    return chart.markers
      .filter((m) => m.timestamp >= primero && m.timestamp <= ultimo)
      .sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
  }, [chart]);

  const alternarIndicador = (nombre: string) => {
    const siguiente = features.includes(nombre)
      ? features.filter((f) => f !== nombre)
      : [...features, nombre];
    actualizar({ features: siguiente.join(",") });
  };

  const aplicarRango = (dias: number | "all") => {
    if (!parElegido) return;
    if (dias === "all") {
      actualizar({ from: parElegido.first_timestamp, to: parElegido.last_timestamp });
      return;
    }
    const fin = new Date(parElegido.last_timestamp);
    const inicio = new Date(fin.getTime() - dias * 86400000);
    actualizar({ from: inicio.toISOString(), to: parElegido.last_timestamp });
  };

  /** Cuantos dias abarca el rango actual, para marcar el atajo activo. */
  const diasDelRango = useMemo(() => {
    if (!from || !to || !parElegido) return null;
    const ms = new Date(to).getTime() - new Date(from).getTime();
    return Math.round(ms / 86400000);
  }, [from, to, parElegido]);

  const hayGrafico = Boolean(symbol && timeframe && from && to);

  return (
    <PageShell wide>
      <PageHeader
        title="Gráficos"
        subtitle="Las velas son las que hay en la base. Los indicadores también: aquí no se calcula nada."
        actions={
          parElegido ? (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {parElegido.total_candles.toLocaleString("es-ES")} velas disponibles
            </span>
          ) : null
        }
      />

      {/* A · Qué miro. */}
      <section className={`${cardClass} mb-4 p-4`}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Símbolo">
            <select
              value={symbol}
              onChange={(e) => {
                const siguiente =
                  grupos.find(
                    (g) => g.symbol === e.target.value && g.timeframe === timeframe,
                  ) ??
                  grupos.find((g) => g.symbol === e.target.value);
                actualizar({
                  symbol: e.target.value || null,
                  timeframe: siguiente?.timeframe ?? null,
                  from: null,
                  to: null,
                  scan: null,
                });
              }}
              className={`${inputClass} w-full`}
            >
              <option value="">Selecciona un símbolo</option>
              {Array.from(new Set(grupos.map((g) => g.symbol))).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Timeframe">
            <select
              value={timeframe}
              onChange={(e) =>
                actualizar({ timeframe: e.target.value || null, from: null, to: null })
              }
              className={`${inputClass} w-full`}
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
          </Field>

          <Field label="Desde">
            <input
              type="date"
              value={from.slice(0, 10)}
              onChange={(e) =>
                actualizar({ from: e.target.value ? `${e.target.value}T00:00:00Z` : null })
              }
              className={`${inputClass} w-full`}
            />
          </Field>

          <Field label="Hasta">
            <input
              type="date"
              value={to.slice(0, 10)}
              onChange={(e) =>
                actualizar({ to: e.target.value ? `${e.target.value}T23:59:59Z` : null })
              }
              className={`${inputClass} w-full`}
            />
          </Field>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {RANGOS.map((rango) => {
            const activo =
              diasDelRango !== null &&
              (rango.dias === "all"
                ? from === parElegido?.first_timestamp
                : Math.abs(diasDelRango - rango.dias) <= 1);
            return (
              <button
                key={rango.etiqueta}
                type="button"
                disabled={!parElegido}
                onClick={() => aplicarRango(rango.dias)}
                className={`rounded-lg border px-2.5 py-1 text-xs font-medium disabled:opacity-40 ${
                  activo
                    ? "border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-300"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {rango.etiqueta}
              </button>
            );
          })}
          {diasDelRango !== null && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {diasDelRango} días de rango
            </span>
          )}
        </div>

        {/* Filtros rápidos de indicadores: chips, y no una lista de casillas.
         *
         *  Aqui se elige «qué superponer» y lo que se elige son pocas cosas a la
         *  vez; una lista de casillas con nombres monoespaciados obliga a leer
         *  para contar. El chip dice el nombre corto y el aviso de cobertura va
         *  encima, porque un indicador sin datos en el rango ensena una linea
         *  que no existe.
         */}
        {symbol && timeframe && (
          <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-800">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                Indicadores
              </span>
              {disponibles.length === 0 ? (
                <span className="text-xs text-slate-400">
                  Este par no tiene ninguno calculado. Créalos en «Indicadores».
                </span>
              ) : (
                disponibles.map((ind) => {
                  const marcado = features.includes(ind.name);
                  const sinCobertura = ausentes.some((a) => a.name === ind.name);
                  return (
                    <button
                      key={ind.name}
                      type="button"
                      onClick={() => alternarIndicador(ind.name)}
                      title={
                        sinCobertura
                          ? `Solo tiene datos de ${formatDateEs(ind.date_from)} a ${formatDateEs(ind.date_to)}`
                          : ind.name
                      }
                      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 font-mono text-xs ${
                        marcado
                          ? "border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-300"
                          : "border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
                      }`}
                    >
                      {sinCobertura && (
                        <TriangleAlert className="h-3 w-3 text-amber-500" />
                      )}
                      {ind.name}
                    </button>
                  );
                })
              )}
              {ausentes.length > 0 && (
                <span className="text-xs text-amber-600 dark:text-amber-400">
                  {ausentes.length} fuera del rango
                </span>
              )}
            </div>
          </div>
        )}

        <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-800">
          <Field label="Escaneo (para marcar detecciones)">
            <select
              value={scan}
              onChange={(e) => actualizar({ scan: e.target.value || null })}
              className={`${inputClass} w-full sm:max-w-md`}
            >
              <option value="">Sin marcadores</option>
              {escaneos.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.label}
                </option>
              ))}
            </select>
          </Field>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Sin escaneo no hay detecciones que marcar: no se puede señalar lo que
            no se ha buscado.
          </p>
        </div>
      </section>

      {error && <p className={errorClass}>{error}</p>}

      {/* B · El grafico, sin panel al lado. */}
      {symbol && timeframe && !from && (
        <p className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Elige un rango para ver el gráfico. Los atajos de arriba cubren lo
          habitual.
        </p>
      )}

      {hayGrafico && chart && (
        <section className="mb-4">
          <UnifiedChart
            rows={filas}
            markers={chart.markers}
            title={`${symbol} · ${timeframe}`}
            timeframe={timeframe}
            subtitle={
              `${formatDateEs(from)} → ${formatDateEs(to)}` +
              (chart.sampled
                ? ` · mostrando ${chart.returned.toLocaleString("es-ES")} de ${chart.total_points.toLocaleString("es-ES")} velas (1 de cada ${chart.step})`
                : ` · ${chart.returned.toLocaleString("es-ES")} velas`)
            }
            highlightTimestamp={foco}
            height={ALTO_GRAFICO}
          />

          {chart.missing_indicators.length > 0 && (
            <p className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
              <TriangleAlert className="h-4 w-4 shrink-0" />
              <span>
                Sin datos en este rango: {chart.missing_indicators.join(", ")}. Se
                han pedido de forma explícita y no tienen ni un punto entre{" "}
                {formatDateEs(from)} y {formatDateEs(to)}.
              </span>
              <Link to="/features/new" className="font-medium underline">
                Calcularlos
              </Link>
            </p>
          )}

          {cargando && (
            <p className="mt-3 flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Cargando velas…
            </p>
          )}
        </section>
      )}

      {/* C · Las detecciones, en texto. */}
      {hayGrafico && chart && (
        <section className={`${cardClass} mb-4 p-4`}>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">
              Detecciones
              {detecciones.length > 0 && (
                <span className="ml-1 text-sm font-normal text-slate-500 dark:text-slate-400">
                  {detecciones.length} en lo que se ve
                </span>
              )}
            </h2>
            {foco && (
              <button
                type="button"
                onClick={() => setFoco(null)}
                className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Ver el rango entero
              </button>
            )}
          </div>

          {detecciones.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
              {scan
                ? "Ninguna deteccion cae dentro de las velas que se ven. Acorta el rango de fechas o sube el muestreo: hay " +
                  `${chart.markers.length} en el rango completo.`
                : "Sin escaneo no hay detecciones que listar."}
            </p>
          ) : (
            <>
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {detecciones.slice(0, MAX_DETECCIONES).map((m) => (
                  <li key={`${m.timestamp}-${m.pattern_name}`}>
                    <button
                      type="button"
                      onClick={() => setFoco(m.timestamp)}
                      className={`flex w-full items-center gap-3 px-2 py-2 text-left text-sm transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                        foco === m.timestamp
                          ? "bg-indigo-50 dark:bg-indigo-950/40"
                          : ""
                      }`}
                    >
                      <Crosshair
                        className={`h-3.5 w-3.5 shrink-0 ${
                          foco === m.timestamp
                            ? "text-indigo-600 dark:text-indigo-400"
                            : "text-slate-300 dark:text-slate-600"
                        }`}
                      />
                      <span className="w-44 shrink-0 tabular-nums text-slate-500 dark:text-slate-400">
                        {formatDateTimeEs(m.timestamp)}
                      </span>
                      <span className="font-medium text-slate-900 dark:text-slate-100">
                        {m.pattern_name}
                      </span>
                      <span
                        className={`text-xs ${
                          m.shape === "arrowUp"
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-rose-600 dark:text-rose-400"
                        }`}
                      >
                        {m.shape === "arrowUp" ? "alcista" : "bajista"}
                      </span>
                      <span className="ml-auto text-xs text-slate-400">
                        {foco === m.timestamp ? "centrada" : "centrar"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {detecciones.length > MAX_DETECCIONES && (
                <p className="mt-3 text-xs text-slate-400">
                  Se muestran {MAX_DETECCIONES} de {detecciones.length}. Acorta el
                  rango para ver el resto.
                </p>
              )}
            </>
          )}
        </section>
      )}

      <p className="flex items-center gap-1.5 text-xs text-slate-400">
        <RefreshCw className="h-3.5 w-3.5" />
        La URL lleva símbolo, timeframe, rango, indicadores y escaneo: la vista se
        puede compartir tal cual.
      </p>
    </PageShell>
  );
}
