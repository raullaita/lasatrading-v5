import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Ban, Database, Loader2, Plus, Send, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { UnifiedChart } from "../../components/charts/UnifiedChart";
import { fromPreviewRows } from "../../components/charts/chartData";
import { IndicatorList } from "../../components/Features/IndicatorList";
import { LogViewer } from "../../components/Features/LogViewer";
import { PreviewModal } from "../../components/Features/PreviewModal";
import { ProgressBar } from "../../components/Features/ProgressBar";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { StatsPanel } from "../../components/Features/StatsPanel";
import {
  cancelFeatureJob,
  clearFeatureJobLogs,
  deleteFeatureJob,
  getFeatureJob,
  getFeatureJobPreview,
  requeueFeatureJob,
} from "../../services/featuresApi";
import { connectFeatureJobLogs, disconnectFeatureJobLogs } from "../../services/featuresWebSocket";
import type { FeatureJobResponse, FeatureLog, FeaturePreviewRow } from "../../types/features";
import { formatDateEs } from "../../utils/format";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export default function FeatureDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<FeatureJobResponse | null>(null);
  const [logs, setLogs] = useState<FeatureLog[]>([]);
  const [previewData, setPreviewData] = useState<FeaturePreviewRow[]>([]);
  /**
   * El merge de filas por timestamp lo hacia el antiguo `FeatureChart` dentro
   * del componente, sin un solo test. Ahora vive en `fromPreviewRows`, que es
   * pura y esta probada, y aqui solo se memoriza.
   */
  const previewRows = useMemo(() => fromPreviewRows(previewData), [previewData]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [requeuing, setRequeuing] = useState(false);
  const [deletingLogs, setDeletingLogs] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const disposedRef = useRef(false);
  const previewLoadedRef = useRef(false);

  const loadPreview = useCallback(async () => {
    if (disposedRef.current) return;
    try {
      const data = await getFeatureJobPreview(jobId, 100);
      if (disposedRef.current) return;
      setPreviewData(data.rows);
      setPreviewError(null);
    } catch (err) {
      if (disposedRef.current) return;
      setPreviewData([]);
      setPreviewError(
        err instanceof Error
          ? `No se pudieron cargar los datos del cálculo: ${err.message}`
          : "No se pudieron cargar los datos del cálculo.",
      );
    }
  }, [jobId]);

  useEffect(() => {
    disposedRef.current = false;
    previewLoadedRef.current = false;
    return () => {
      disposedRef.current = true;
      disconnectFeatureJobLogs(jobId);
    };
  }, [jobId]);

  useEffect(() => {
    const disconnect = connectFeatureJobLogs(jobId, {
      onLog: (log) => setLogs((prev) => [...prev, log]),
      onConnectionChange: setWsConnected,
      onError: (message) => setError(message),
    });
    return disconnect;
  }, [jobId]);

  useEffect(() => {
    const present = (next: FeatureJobResponse) => {
      if (disposedRef.current) return;
      setJob(next);
      setLoading(false);
      setError(null);
      if (TERMINAL.has(next.status)) {
        disconnectFeatureJobLogs(jobId);
        if (!previewLoadedRef.current) {
          previewLoadedRef.current = true;
          void loadPreview();
        }
      }
    };

    void getFeatureJob(jobId)
      .then(present)
      .catch(() => {
        if (!disposedRef.current) {
          setError("Job no encontrado.");
          setLoading(false);
        }
      });

    const timer = window.setInterval(() => {
      void getFeatureJob(jobId)
        .then((next) => {
          present(next);
          if (TERMINAL.has(next.status)) {
            window.clearInterval(timer);
          }
        })
        .catch(() => undefined);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [jobId, loadPreview]);

  async function onCancel() {
    if (!window.confirm("¿Cancelar este cálculo? El trabajo se detendrá en el siguiente chunk.")) {
      return;
    }
    setCancelling(true);
    try {
      const updated = await cancelFeatureJob(jobId);
      setJob(updated);
    } catch {
      setError("No se pudo cancelar el cálculo.");
    } finally {
      setCancelling(false);
    }
  }

  async function onRequeue() {
    if (
      !window.confirm("Este job está pendiente o sin progreso. ¿Reenviarlo a la cola de Celery?")
    ) {
      return;
    }
    setRequeuing(true);
    try {
      const updated = await requeueFeatureJob(jobId);
      setJob(updated);
    } catch {
      setError("No se pudo reenviar el job a la cola.");
    } finally {
      setRequeuing(false);
    }
  }

  async function onDeleteLogs() {
    if (!window.confirm("¿Borrar los logs de este job?")) return;
    setDeletingLogs(true);
    try {
      await clearFeatureJobLogs(jobId);
      setLogs([]);
    } catch {
      setError("No se pudieron borrar los logs.");
    } finally {
      setDeletingLogs(false);
    }
  }

  async function onDelete() {
    if (!window.confirm("¿Borrar este job y sus datos de features?")) return;
    setDeleting(true);
    try {
      await deleteFeatureJob(jobId);
      navigate("/features");
    } catch {
      setError("No se pudo borrar el job.");
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
      </main>
    );
  }

  if (error || !job) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8 dark:bg-slate-950">
        <div className="text-center">
          <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {error ?? "Sin datos"}
          </p>
          <Link
            to="/features"
            className="mt-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Volver a cálculos
          </Link>
        </div>
      </main>
    );
  }

  const live = !TERMINAL.has(job.status);
  const startedAt = job.started_at ? new Date(job.started_at).getTime() : null;
  const staleProcessing =
    job.status === "processing" &&
    startedAt !== null &&
    Date.now() - startedAt > 5 * 60_000 &&
    job.processed_candles === 0;
  const needsRequeue = job.status === "pending" || staleProcessing;
  const progress =
    job.total_candles > 0 ? Math.round((job.processed_candles / job.total_candles) * 100) : 0;

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-6xl">
        <Link
          to="/features"
          className="text-sm text-indigo-600 hover:underline dark:text-indigo-400"
        >
          ← Cálculos
        </Link>

        <div className="mb-6 mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <StatusBadge status={job.status} />
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {job.symbol} · {job.timeframe}
            </h1>
          </div>
          {live ? (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void onCancel()}
                disabled={cancelling}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:hover:bg-rose-950/50"
              >
                <Ban className="h-4 w-4" />
                {cancelling ? "Cancelando…" : "Cancelar"}
              </button>
              {needsRequeue && (
                <button
                  type="button"
                  onClick={() => void onRequeue()}
                  disabled={requeuing}
                  className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 dark:border-emerald-900 dark:bg-slate-900 dark:hover:bg-emerald-950/50"
                >
                  <Send className={`h-4 w-4 ${requeuing ? "animate-pulse" : ""}`} />
                  {requeuing ? "Reenviando…" : "Reenviar a cola"}
                </button>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
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
                {deleting ? "Borrando…" : "Borrar job"}
              </button>
              <button
                type="button"
                onClick={() => setShowPreview(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                <Database className="h-4 w-4" />
                Ver datos
              </button>
              <Link
                to="/features/new"
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                <Plus className="h-4 w-4" />
                Nuevo cálculo
              </Link>
            </div>
          )}
        </div>

        <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Meta label="Fecha inicial" value={formatDateEs(job.date_from)} />
          <Meta label="Fecha final" value={formatDateEs(job.date_to)} />
          <Meta
            label="Indicadores"
            value={job.indicators_config.map((i) => i.name).join(", ") || "Sin configurar"}
          />
        </div>

        {live && (
          <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {wsConnected ? "Progreso en vivo" : "Calculando…"}
              </span>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {job.processed_candles}/{job.total_candles} velas ({progress}%)
              </span>
            </div>
            <ProgressBar current={job.processed_candles} total={job.total_candles} />
          </div>
        )}

        <div className="mb-6">
          {live ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <IndicatorList indicators={job.indicators_config} />
              <LogViewer logs={logs} />
            </div>
          ) : (
            <div className="space-y-4">
              <StatsPanel job={job} />
              <IndicatorList indicators={job.indicators_config} />
              <LogViewer logs={logs} />
              {previewError && (
                <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
                  {previewError}
                </p>
              )}
              <UnifiedChart
                rows={previewRows}
                title={`${job.symbol} · ${job.timeframe}`}
                subtitle={`${previewData.length.toLocaleString("es-ES")} velas con los indicadores del job`}
              />
            </div>
          )}
        </div>
      </div>
      {showPreview && <PreviewModal jobId={jobId} onClose={() => setShowPreview(false)} />}
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
