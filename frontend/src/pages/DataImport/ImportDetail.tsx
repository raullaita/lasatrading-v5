import { useEffect, useRef, useState } from "react";

import { Ban, Database, Loader2, Plus, RefreshCcw, Send } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CombinationList } from "../../components/DataImport/CombinationList";
import { LogViewer } from "../../components/DataImport/LogViewer";
import { PreviewModal } from "../../components/DataImport/PreviewModal";
import { ProgressBar } from "../../components/DataImport/ProgressBar";
import { StatusBadge } from "../../components/DataImport/StatusBadge";
import { StatsPanel } from "../../components/DataImport/StatsPanel";
import { cancelImport, getJobStatus, getStats, requeueJob, retryJob } from "../../services/api";
import { connectJobLogs, disconnectJobLogs } from "../../services/websocket";
import type { ImportJob, ImportLog, ImportStats } from "../../types/dataImport";
import { formatDateEs } from "../../utils/format";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export default function ImportDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<ImportJob | null>(null);
  const [logs, setLogs] = useState<ImportLog[]>([]);
  const [stats, setStats] = useState<ImportStats | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [requeuing, setRequeuing] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const disposedRef = useRef(false);

  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      disconnectJobLogs(jobId);
    };
  }, [jobId]);

  useEffect(() => {
    const disconnect = connectJobLogs(jobId, {
      onLog: (log) => setLogs((prev) => [...prev, log]),
      onConnectionChange: setWsConnected,
      onError: (message) => setError(message),
    });
    return disconnect;
  }, [jobId]);

  useEffect(() => {
    const present = (next: ImportJob) => {
      if (disposedRef.current) return;
      setJob(next);
      setLoading(false);
      setError(null);
      if (TERMINAL.has(next.status)) {
        disconnectJobLogs(jobId);
        void getStats(jobId)
          .then(setStats)
          .catch(() => undefined);
      }
    };

    void getJobStatus(jobId)
      .then(present)
      .catch(() => {
        if (!disposedRef.current) {
          setError("Job no encontrado.");
          setLoading(false);
        }
      });

    const timer = window.setInterval(() => {
      void getJobStatus(jobId)
        .then((next) => {
          present(next);
          if (TERMINAL.has(next.status)) {
            window.clearInterval(timer);
          }
        })
        .catch(() => undefined);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [jobId]);

  const onCancel = async () => {
    if (!window.confirm("¿Cancelar esta importación? El trabajo se detendrá en el siguiente chunk.")) {
      return;
    }
    setCancelling(true);
    try {
      const updated = await cancelImport(jobId);
      setJob(updated);
    } catch {
      setError("No se pudo cancelar la importación.");
    } finally {
      setCancelling(false);
    }
  };

  const onRetry = async () => {
    if (!window.confirm("¿Reintentar las combinaciones fallidas o canceladas como un nuevo job?")) {
      return;
    }
    setRetrying(true);
    try {
      const { job_id } = await retryJob(jobId);
      navigate(`/import/${job_id}`);
    } catch {
      setError("No se pudo crear el job de reintento.");
      setRetrying(false);
    }
  };

  const onRequeue = async () => {
    if (
      !window.confirm(
        "Este job está pendiente o sin progreso. ¿Reenviarlo a la cola de Celery?",
      )
    ) {
      return;
    }
    setRequeuing(true);
    try {
      const updated = await requeueJob(jobId);
      setJob(updated);
    } catch {
      setError("No se pudo reenviar el job a la cola.");
      setRequeuing(false);
    }
  };

  if (loading) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
      </main>
    );
  }

  if (error || !job) {
    return (
      <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8">
        <div className="text-center">
          <p className="text-lg font-semibold text-slate-900">{error ?? "Sin datos"}</p>
          <Link to="/import" className="mt-2 inline-block text-sm text-indigo-600 hover:underline">
            Volver a importaciones
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
    job.completed_combinations === 0 &&
    job.failed_combinations === 0;
  const needsRequeue = job.status === "pending" || staleProcessing;
  const progress =
    job.total_combinations > 0
      ? ((job.completed_combinations + job.failed_combinations) / job.total_combinations) * 100
      : 0;

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto max-w-5xl">
        <Link to="/import" className="text-sm text-indigo-600 hover:underline">
          ← Importaciones
        </Link>

        <div className="mb-6 mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <StatusBadge status={job.status} />
            <h1 className="text-2xl font-bold text-slate-900">
              {job.symbols.join(", ")} · {job.timeframes.join(", ")}
            </h1>
          </div>
          {live && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void onCancel()}
                disabled={cancelling}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
              >
                <Ban className="h-4 w-4" />
                {cancelling ? "Cancelando…" : "Cancelar"}
              </button>
              {needsRequeue && (
                <button
                  type="button"
                  onClick={() => void onRequeue()}
                  disabled={requeuing}
                  className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                >
                  <Send className={`h-4 w-4 ${requeuing ? "animate-pulse" : ""}`} />
                  {requeuing ? "Reenviando…" : "Reenviar a cola"}
                </button>
              )}
            </div>
          )}
          {!live && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setShowPreview(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                <Database className="h-4 w-4" />
                Ver datos
              </button>
              {(job.failed_combinations > 0 ||
                job.combinations.some((c) => c.status === "cancelled")) && (
                <button
                  type="button"
                  onClick={() => void onRetry()}
                  disabled={retrying}
                  className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                >
                  <RefreshCcw className={`h-4 w-4 ${retrying ? "animate-spin" : ""}`} />
                  {retrying ? "Creando…" : "Reintentar fallidas"}
                </button>
              )}
              <Link
                to="/import/new"
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                <Plus className="h-4 w-4" />
                Nueva importación
              </Link>
            </div>
          )}
        </div>

        <div className="mb-4 grid grid-cols-3 gap-4">
          <Meta label="Modo" value={job.import_mode} />
          <Meta label="Fecha inicial" value={formatDateEs(job.date_from)} />
          <Meta label="Fecha final" value={formatDateEs(job.date_to)} />
        </div>

        {live && (
          <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">
                {wsConnected ? "Progreso en vivo" : "Procesando…"}
              </span>
              <span className="text-sm text-slate-500">
                {job.completed_combinations + job.failed_combinations}/{job.total_combinations}{" "}
                combinaciones
              </span>
            </div>
            <ProgressBar value={progress} />
          </div>
        )}

        <div className="mb-6">
          {live ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <CombinationList combinations={job.combinations} />
              <LogViewer logs={logs} />
            </div>
          ) : (
            <div className="space-y-4">
              <StatsPanel stats={stats} />
              <CombinationList combinations={job.combinations} />
              <LogViewer logs={logs} />
            </div>
          )}
        </div>
      </div>
      {showPreview && (
        <PreviewModal
          jobId={jobId}
          combinations={job.combinations}
          onClose={() => setShowPreview(false)}
        />
      )}
    </main>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs capitalize text-slate-500">{label}</p>
      <p className="mt-0.5 text-sm font-medium text-slate-800">{value}</p>
    </div>
  );
}