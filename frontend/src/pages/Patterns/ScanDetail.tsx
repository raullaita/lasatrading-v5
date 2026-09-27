import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Ban, Loader2, Plus, Send, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ProgressBar } from "../../components/Features/ProgressBar";
import { LogViewer } from "../../components/Patterns/LogViewer";
import { OccurrenceTable } from "../../components/Patterns/OccurrenceTable";
import { PatternBreakdown } from "../../components/Patterns/PatternBreakdown";
import { PatternChart } from "../../components/Patterns/PatternChart";
import { summarizeOccurrences } from "../../components/Patterns/patternUtils";
import { StatusBadge } from "../../components/ui/StatusBadge";
import {
  cancelPatternScan,
  clearPatternScanLogs,
  deletePatternScan,
  getPatternCatalog,
  getPatternScan,
  getPatternScanChart,
  getPatternScanOccurrences,
  requeuePatternScan,
} from "../../services/patternsApi";
import {
  connectPatternScanLogs,
  disconnectPatternScanLogs,
} from "../../services/patternsWebSocket";
import {
  PATTERN_TERMINAL_STATUSES,
  type PatternChartData,
  type PatternDefinition,
  type PatternOccurrence,
  type PatternScanJobResponse,
  type PatternScanLog,
} from "../../types/patterns";
import { formatDateEs } from "../../utils/format";

/** Tope del backend en `/scans/{id}/occurrences`. */
const OCCURRENCE_PAGE_SIZE = 100;

/** Igual que en `FeatureDetail`: 5 min sin procesar nada es un job colgado. */
const STALE_AFTER_MS = 5 * 60_000;

export default function ScanDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [job, setJob] = useState<PatternScanJobResponse | null>(null);
  const [logs, setLogs] = useState<PatternScanLog[]>([]);
  const [occurrences, setOccurrences] = useState<PatternOccurrence[]>([]);
  const [occurrenceTotal, setOccurrenceTotal] = useState(0);
  const [occPage, setOccPage] = useState(1);
  const [chart, setChart] = useState<PatternChartData | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<PatternDefinition[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  /**
   * Fallo al cargar el job. Es el único error que sustituye la pagina entera,
   * porque sin job no hay nada que mostrar y el resto de la vista dependeria de
   * datos que no existen. Los fallos de los botones van a `actionError` y se
   * muestran como aviso: fallar al cancelar no significa que el escaneo haya
   * desaparecido.
   */
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  /**
   * El WebSocket tiene su propio error y no comparte el de la página.
   *
   * El socket se cae cada vez que el backend reinicia o duerme entre trabajos,
   * y es un problema de connectivity, no del escaneo: si su mensaje fuera a
   * `error` comparte el `return` temprano del render y la pantalla entera se
   * sustituiría por «Escaneo no encontrado», dejando al usuario sin salida
   * hasta recargar. Aquí solo pinta un aviso; los logs se reconectan solos.
   */
  const [wsError, setWsError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [requeuing, setRequeuing] = useState(false);
  const [deletingLogs, setDeletingLogs] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const disposedRef = useRef(false);
  const chartLoadedRef = useRef(false);
  /**
   * Número de intento de este job, no su id.
   *
   * El backend cierra el WebSocket y el sondeo al llegar a un estado final, así
   * que tras pulsar «Reenviar» un job fallido se queda sin logs y sin polling si
   * los dos efectos dependen solo de `jobId`: React no los vuelve a montar. Este
   * contador se incrementa en cada reenvío y ambos efectos lo usan como
   * dependencia, con lo que se reconectan y vuelven a preguntar por el estado
   * sin tocar nada más.
   */
  const [attempt, setAttempt] = useState(0);

  /** Vela a la que hay que centrar el gráfico. Llega por `?ts=` desde la tabla global. */
  const highlight = searchParams.get("ts");

  const loadOccurrences = useCallback(async () => {
    if (disposedRef.current) return;
    try {
      const data = await getPatternScanOccurrences(jobId, {
        page: occPage,
        page_size: OCCURRENCE_PAGE_SIZE,
      });
      if (disposedRef.current) return;
      setOccurrences(data.occurrences);
      setOccurrenceTotal(data.total);
    } catch {
      if (!disposedRef.current) setOccurrenceTotal(0);
    }
  }, [jobId, occPage]);

  /**
   * Catálogo de patrones, solo para saber qué indicadores exige cada uno.
   *
   * `GET /scans/{id}/chart` no devuelve líneas de indicadores por su cuenta: hay que
   * pedirlos con `features`, y sin ese parámetro el gráfico sale limpio de
   * cualquier trazo sobre las velas. Se cargan aquí los que el job utilizó de
   * verdad, no todos los del par: son los que explican por qué saltó la
   * detección.
   */
  useEffect(() => {
    void getPatternCatalog()
      .then(setCatalog)
      .catch(() => setCatalog([]));
  }, []);

  useEffect(() => {
    disposedRef.current = false;
    chartLoadedRef.current = false;
    return () => {
      disposedRef.current = true;
      disconnectPatternScanLogs(jobId);
    };
  }, [jobId]);

  useEffect(() => {
    const disconnect = connectPatternScanLogs(jobId, {
      onLog: (log) => setLogs((prev) => [...prev, log]),
      onConnectionChange: setWsConnected,
      onError: (message) => setWsError(message),
    });
    setWsError(null);
    return disconnect;
  }, [jobId, attempt]);

  /**
   * CSV de indicadores a dibujar, derivado de los patrones del job.
   *
   * Es un string y no un array a propósito: `useCallback` compara sus
   * dependencias por identidad, y un array nuevo en cada sondeo (cada 2 s)
   * recrearía `loadChart` y remontaría el efecto de sondeo sin parar. Dos
   * strings con el mismo contenido son el mismo valor, así que el sondeo no se
   * reinicia aunque `job` cambie de referencia.
   */
  const featuresParam = useMemo(() => {
    if (!job) return "";
    const codes = new Set(job.patterns_config.map((p) => p.code));
    const feats = new Set<string>();
    for (const definition of catalog) {
      if (!codes.has(definition.code)) continue;
      for (const feature of definition.required_features) feats.add(feature);
    }
    return [...feats].join(",");
  }, [job, catalog]);

  const loadChart = useCallback(async () => {
    try {
      const data = await getPatternScanChart(jobId, {
        features: featuresParam ? featuresParam.split(",") : undefined,
      });
      if (!disposedRef.current) {
        setChart(data);
        setChartError(null);
      }
    } catch {
      if (!disposedRef.current) {
        setChart(null);
        setChartError("No se pudo cargar el gráfico de este escaneo.");
      }
    }
  }, [jobId, featuresParam]);

  useEffect(() => {
    const present = (next: PatternScanJobResponse) => {
      if (disposedRef.current) return;
      setJob(next);
      setLoading(false);
      setLoadError(null);
      if (PATTERN_TERMINAL_STATUSES.includes(next.status)) {
        // El backend cierra el socket al llegar a un estado final: dejarlo
        // abierto solo gastaria reintentos del cliente contra un socket muerto.
        // El gráfico no se pide aquí: depende del catálogo, y hay otro efecto
        // que espera a tener las dos cosas.
        disconnectPatternScanLogs(jobId);
      }
    };

    void getPatternScan(jobId)
      .then(present)
      .catch(() => {
        if (!disposedRef.current) {
          setLoadError("Escaneo no encontrado.");
          setLoading(false);
        }
      });

    const timer = window.setInterval(() => {
      void getPatternScan(jobId)
        .then((next) => {
          present(next);
          if (PATTERN_TERMINAL_STATUSES.includes(next.status)) {
            window.clearInterval(timer);
          }
        })
        .catch(() => undefined);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [jobId, loadChart, attempt]);

  /**
   * El gráfico se pide cuando el job termina **y** ya se sabe qué indicadores
   * dibujar. Son las dos condiciones, no una: si un escaneo se completa en dos
   * segundos y el catálogo aún no ha llegado, pedirlo en ese momento devolvería
   * un gráfico sin ninguna línea y `chartLoadedRef` impediría pedirlo después.
   */
  useEffect(() => {
    if (!job) return;
    if (!PATTERN_TERMINAL_STATUSES.includes(job.status)) return;
    if (catalog.length === 0) return;
    if (chartLoadedRef.current) return;
    chartLoadedRef.current = true;
    void loadChart();
  }, [job, catalog, loadChart]);

  useEffect(() => {
    void loadOccurrences();
  }, [loadOccurrences]);

  async function onCancel() {
    if (!window.confirm("¿Cancelar este escaneo? El trabajo se detendrá en el siguiente tramo.")) {
      return;
    }
    setCancelling(true);
    setActionError(null);
    try {
      setJob(await cancelPatternScan(jobId));
    } catch {
      setActionError("No se pudo cancelar el escaneo.");
    } finally {
      setCancelling(false);
    }
  }

  async function onRequeue() {
    if (!window.confirm("¿Reenviar este escaneo a la cola de Celery?")) return;
    setRequeuing(true);
    setActionError(null);
    try {
      setJob(await requeuePatternScan(jobId));
      // El gráfico que se cargó para el intento fallido ya no vale, y el
      // sondeo y el socket están parados desde que el job llegó a su estado
      // final. Subir `attempt` los rearma a los dos a la vez.
      chartLoadedRef.current = false;
      setChart(null);
      setAttempt((n) => n + 1);
    } catch {
      setActionError("No se pudo reenviar el escaneo.");
    } finally {
      setRequeuing(false);
    }
  }

  async function onDeleteLogs() {
    if (!window.confirm("¿Borrar los logs de este escaneo?")) return;
    setDeletingLogs(true);
    setActionError(null);
    try {
      await clearPatternScanLogs(jobId);
      setLogs([]);
    } catch {
      setActionError("No se pudieron borrar los logs.");
    } finally {
      setDeletingLogs(false);
    }
  }

  async function onDelete() {
    if (!window.confirm("¿Borrar este escaneo, sus ocurrencias y sus logs?")) return;
    setDeleting(true);
    setActionError(null);
    try {
      await deletePatternScan(jobId);
      navigate("/patterns");
    } catch {
      setActionError("No se pudo borrar el escaneo.");
      setDeleting(false);
    }
  }

  const summary = useMemo(() => summarizeOccurrences(occurrences), [occurrences]);

  /** ¿El resumen cubre todo el job o solo la página cargada? */
  const summaryIsPartial = occurrences.length < occurrenceTotal;

  if (loading) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
      </main>
    );
  }

  if (loadError || !job) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8 dark:bg-slate-950">
        <div className="text-center">
          <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {loadError ?? "Sin datos"}
          </p>
          <Link
            to="/patterns"
            className="mt-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Volver a escaneos
          </Link>
        </div>
      </main>
    );
  }

  const live = !PATTERN_TERMINAL_STATUSES.includes(job.status);
  const startedAt = job.started_at ? new Date(job.started_at).getTime() : null;
  const staleProcessing =
    job.status === "processing" &&
    startedAt !== null &&
    Date.now() - startedAt > STALE_AFTER_MS &&
    job.processed_candles === 0;
  // `failed` también se puede reencolar: es el camino natural cuando el job
  // murió por MissingFeaturesError, ya calculadas.
  const needsRequeue = job.status === "pending" || job.status === "failed" || staleProcessing;
  const occPages = Math.max(1, Math.ceil(occurrenceTotal / OCCURRENCE_PAGE_SIZE));

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-6xl">
        <Link
          to="/patterns"
          className="text-sm text-indigo-600 hover:underline dark:text-indigo-400"
        >
          ← Escaneos
        </Link>

        <div className="mb-6 mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <StatusBadge status={job.status} />
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {job.symbol} · {job.timeframe}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {live && (
              <button
                type="button"
                onClick={() => void onCancel()}
                disabled={cancelling}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:hover:bg-rose-950/50"
              >
                <Ban className="h-4 w-4" />
                {cancelling ? "Cancelando…" : "Cancelar"}
              </button>
            )}
            {needsRequeue && (
              <button
                type="button"
                onClick={() => void onRequeue()}
                disabled={requeuing}
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 dark:border-emerald-900 dark:bg-slate-900 dark:hover:bg-emerald-950/50"
              >
                <Send className={`h-4 w-4 ${requeuing ? "animate-pulse" : ""}`} />
                {requeuing ? "Reenviando…" : "Reenviar"}
              </button>
            )}
            <button
              type="button"
              onClick={() => void onDeleteLogs()}
              disabled={deletingLogs}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Trash2 className="h-4 w-4" />
              {deletingLogs ? "Borrando…" : "Borrar logs"}
            </button>
            <button
              type="button"
              onClick={() => void onDelete()}
              disabled={deleting}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:hover:bg-rose-950/50"
            >
              <Trash2 className="h-4 w-4" />
              {deleting ? "Borrando…" : "Borrar escaneo"}
            </button>
            <Link
              to={`/patterns/new?pattern=${job.patterns_config[0]?.code ?? ""}`}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              <Plus className="h-4 w-4" />
              Nuevo escaneo
            </Link>
          </div>
        </div>

        {actionError && (
          <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            {actionError}
          </p>
        )}

        {wsError && (
          <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
            Logs en directo no disponibles: {wsError}. El progreso y el resultado del escaneo se
            siguen actualizando; los logs se reconectan solos.
          </p>
        )}

        {job.error_message && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 dark:border-rose-900 dark:bg-rose-950/40">
            <p className="text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
              Error del escaneo
            </p>
            <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-rose-700 dark:text-rose-300">
              {job.error_message}
            </p>
            {job.status === "failed" && (
              <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                Si el fallo fue por features ausentes, caláculas en «Indicadores» y usa «Reenviar»:
                conserva el rango y los parámetros ya elegidos.
              </p>
            )}
          </div>
        )}

        <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Meta label="Fecha inicial" value={formatDateEs(job.date_from)} />
          <Meta label="Fecha final" value={formatDateEs(job.date_to)} />
          <Meta
            label="Patrones"
            value={job.patterns_config.map((p) => p.code).join(", ") || "Sin configurar"}
          />
          <Meta label="Ocurrencias" value={occurrenceTotal.toLocaleString("es-ES")} />
        </div>

        {live && (
          <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {wsConnected ? "Progreso en vivo" : "Escaneando…"}
              </span>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {job.processed_candles.toLocaleString("es-ES")}/
                {job.total_candles.toLocaleString("es-ES")} velas
              </span>
            </div>
            <ProgressBar current={job.processed_candles} total={job.total_candles} />
          </div>
        )}

        <div className="mb-6 space-y-4">
          <LogViewer logs={logs} />
        </div>

        <div className="mb-6 space-y-4">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Resumen</h2>
          {occurrences.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {live
                ? "Todavía no hay detecciones. Los resultados aparecerán al terminar el escaneo."
                : "Este escaneo no detectó ningún patrón."}
            </p>
          ) : (
            <>
              <PatternBreakdown summary={summary} />
              {summaryIsPartial && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  El desglose cubre las {occurrences.length.toLocaleString("es-ES")} ocurrencias
                  cargadas en esta página, no las {occurrenceTotal.toLocaleString("es-ES")} del
                  escaneo. El resumen completo por escaneo no lo expone la API: `GET
                  /occurrences/summary` no acepta `job_id`.
                </p>
              )}
            </>
          )}
        </div>

        <div className="mb-6 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Ocurrencias</h2>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {occurrenceTotal.toLocaleString("es-ES")} detecciones
            </span>
          </div>
          <OccurrenceTable
            occurrences={occurrences}
            onViewChart={(timestamp) => setSearchParams({ ts: timestamp })}
            emptyMessage={
              live
                ? "Aún no hay ocurrencias. Aparecen cuando el escaneo termina."
                : "Sin ocurrencias."
            }
          />
          {occPages > 1 && (
            <div className="flex items-center justify-between">
              <button
                type="button"
                disabled={occPage <= 1}
                onClick={() => setOccPage((p) => p - 1)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
              >
                Anterior
              </button>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Página {occPage} de {occPages}
              </span>
              <button
                type="button"
                disabled={occPage >= occPages}
                onClick={() => setOccPage((p) => p + 1)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
              >
                Siguiente
              </button>
            </div>
          )}
        </div>

        <div className="space-y-3">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Gráfico</h2>
          {chartError && (
            <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
              {chartError}
            </p>
          )}
          {chart ? (
            <PatternChart
              candles={chart.candles}
              indicators={chart.indicators}
              markers={chart.markers}
              symbol={chart.symbol}
              timeframe={chart.timeframe}
              highlightTimestamp={highlight}
            />
          ) : (
            !chartError && (
              <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                {live
                  ? "El gráfico se carga cuando el escaneo termina."
                  : "Sin datos para graficar."}
              </p>
            )
          )}
          {highlight && (
            <p className="text-xs text-indigo-600 dark:text-indigo-400">
              Centrado en la vela de {new Date(highlight).toLocaleString("es-ES")}.{" "}
              <button
                type="button"
                onClick={() => setSearchParams({})}
                className="underline hover:no-underline"
              >
                Quitar el resaltado
              </button>
            </p>
          )}
        </div>
      </div>
    </main>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs capitalize text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-0.5 truncate text-sm font-medium text-slate-800 dark:text-slate-200">
        {value}
      </p>
    </div>
  );
}
