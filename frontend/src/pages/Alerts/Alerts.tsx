import { useCallback, useEffect, useState } from "react";

import { BellRing, Loader2, Plus, Radio, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { CoverageBadge, ValidationBadge } from "../../components/Alerts/ValidationBadge";
import {
  deleteAlertRule,
  getAlertRules,
  getAlerts,
  probeTelegram,
  setAlertRuleEnabled,
} from "../../services/alertsApi";
import { connectAlertStream } from "../../services/alertsWebSocket";
import {
  ALERT_STATUS_LABELS,
  type Alert,
  type AlertRule,
  type AlertValidationStatus,
  type TelegramProbeOut,
} from "../../types/alerts";
import { formatDateTimeEs, toNumber } from "../../utils/format";

/**
 * Pantalla de alertas: reglas, historial y canal.
 *
 * El orden de las tres cosas es deliberado y es el orden de las preguntas que se
 * hace el usuario: **¿funciona el canal?**, **¿qué estoy vigilando y con qué
 * respaldo?**, **¿qué ha pasado?**. El canal va primero porque si está roto todo
 * lo demás es teatro, y una pantalla donde el canal se comprueba en un menú
 * secundario esconde justo el fallo que más tiempo cuesta diagnosticar.
 */
export default function Alerts() {
  const [reglas, setReglas] = useState<AlertRule[]>([]);
  const [alertas, setAlertas] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const [canal, setCanal] = useState<TelegramProbeOut | null>(null);
  const [probando, setProbando] = useState(false);
  const [enVivo, setEnVivo] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      const [rs, as] = await Promise.all([getAlertRules(), getAlerts(1)]);
      setReglas(rs);
      setAlertas(as.alerts);
      setTotal(as.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  /**
   * Lo que llega por el socket es solo un identificador, y la fila se pide por
   * HTTP. Es lo que hace que lo que se ve en pantalla no pueda divergir de lo
   * que hay en la base.
   */
  useEffect(() => {
    return connectAlertStream({
      onAlert: (alertId) => {
        void getAlerts(1).then((as) => {
          setAlertas(as.alerts);
          setTotal(as.total);
        });
        void alertId;
      },
      onConnectionChange: setEnVivo,
      onError: setError,
    });
  }, []);

  const probar = async () => {
    setProbando(true);
    try {
      setCanal(await probeTelegram());
    } catch (err) {
      setCanal({
        ok: false,
        skipped: false,
        message_id: null,
        error: err instanceof Error ? err.message : "Falló la prueba",
        pista: null,
      });
    } finally {
      setProbando(false);
    }
  };

  const alternar = async (regla: AlertRule) => {
    setReglas((previas) =>
      previas.map((r) => (r.id === regla.id ? { ...r, enabled: !r.enabled } : r)),
    );
    try {
      await setAlertRuleEnabled(regla.id, !regla.enabled);
    } catch {
      void cargar();
    }
  };

  const borrar = async (regla: AlertRule) => {
    if (!window.confirm(`¿Borrar la regla «${regla.name}» y sus avisos?`)) return;
    try {
      await deleteAlertRule(regla.id);
      await cargar();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo borrar");
    }
  };

  const validadas = reglas.filter((r) => VALIDADA.has(r.validation_status)).length;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Alertas</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Avisos de patrones que aparecen en tus datos, con la configuración que alguien validó y
            el veredicto que tiene. La herramienta informa;{" "}
            <strong>la decisión de operar es tuya</strong>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 text-xs ${
              enVivo ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"
            }`}
          >
            <Radio className="h-3.5 w-3.5" />
            {enVivo ? "en vivo" : "sin conexión en vivo"}
          </span>
          <Link
            to="/alerts/new"
            className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white"
          >
            <Plus className="h-4 w-4" /> Nueva regla
          </Link>
          <button
            type="button"
            onClick={() => void cargar()}
            className="rounded border border-slate-300 px-2 py-1.5 dark:border-slate-600"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </div>
      )}

      {/* 1 · El canal, primero. Si está roto, todo lo demás es teatro. */}
      <section className="rounded border border-slate-200 p-4 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-medium">Canal de Telegram</h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              La causa número uno de «las alertas no me llegan» es de configuración, y descubrirlo
              esperando una detección real es esperar horas para enterarte de un dedo que no se
              movió.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void probar()}
            disabled={probando}
            className="inline-flex items-center gap-2 rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            {probando ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <BellRing className="h-4 w-4" />
            )}
            Probar el canal
          </button>
        </div>
        {canal && (
          <div
            className={`mt-3 rounded border p-3 text-sm ${
              canal.ok
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40"
                : "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40"
            }`}
          >
            <p className="font-medium">
              {canal.ok
                ? `Mensaje entregado (id ${canal.message_id}). Debería estar en tu chat.`
                : canal.skipped
                  ? "El canal está apagado: no se intentó enviar nada."
                  : "El canal no responde."}
            </p>
            {canal.pista && <p className="mt-1">{canal.pista}</p>}
            {canal.error && !canal.pista && (
              <p className="mt-1 font-mono text-xs opacity-80">{canal.error}</p>
            )}
          </div>
        )}
      </section>

      {/* 2 · Las reglas y su respaldo. */}
      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <h2 className="font-medium">Reglas ({reglas.length})</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {validadas} de {reglas.length} con evidencia que no es un descarte
          </p>
        </div>
        {cargando ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : reglas.length === 0 ? (
          <div className="rounded border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-600">
            No hay reglas. Crea una y el sistema avisará cuando aparezca el patrón.
          </div>
        ) : (
          <div className="space-y-3">
            {reglas.map((regla) => (
              <ReglaCard
                key={regla.id}
                regla={regla}
                onToggle={() => void alternar(regla)}
                onDelete={() => void borrar(regla)}
              />
            ))}
          </div>
        )}
      </section>

      {/* 3 · El historial. */}
      <section className="space-y-2">
        <h2 className="font-medium">Historial ({total})</h2>
        {alertas.length === 0 ? (
          <p className="rounded border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-600">
            Todavía no ha saltado ninguna alerta.
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left dark:bg-slate-800">
                <tr>
                  <th className="px-2 py-2">Vela (UTC)</th>
                  <th className="px-2 py-2">Símbolo</th>
                  <th className="px-2 py-2">Patrón</th>
                  <th className="px-2 py-2 text-right">Referencia</th>
                  <th className="px-2 py-2">Entrega</th>
                </tr>
              </thead>
              <tbody>
                {alertas.map((alerta) => (
                  <tr key={alerta.id} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="px-2 py-2 whitespace-nowrap">
                      {formatDateTimeEs(alerta.signal_timestamp)}
                    </td>
                    <td className="px-2 py-2 whitespace-nowrap">
                      {alerta.symbol} {alerta.timeframe}
                    </td>
                    <td className="px-2 py-2 whitespace-nowrap">{alerta.pattern_name}</td>
                    <td className="px-2 py-2 text-right tabular-nums">
                      {toNumber(alerta.reference_price)?.toFixed(2) ?? "—"}
                    </td>
                    <td className="px-2 py-2">
                      <EntregaCelda alerta={alerta} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * Los dos estados que no son «entregada» y que se distinguen a propósito.
 *
 * `skipped` no es `failed`: `skipped` es «no se intentó porque el canal estaba
 * apagado» y `failed` es «se intentó y no llegó». Enseñar los dos como «no
 * enviada» hace que apagar el sistema y un fallo de red parezcan lo mismo, que
 * es justo la confusión que hace imposible responder a «¿llegó?».
 */
function EntregaCelda({ alerta }: { alerta: Alert }) {
  const tono: Record<string, string> = {
    sent: "text-emerald-600 dark:text-emerald-400",
    failed: "text-rose-600 dark:text-rose-400",
    skipped: "text-amber-600 dark:text-amber-400",
    pending: "text-slate-500",
  };
  return (
    <span className={tono[alerta.status]} title={alerta.delivery_error ?? undefined}>
      {ALERT_STATUS_LABELS[alerta.status]}
      {alerta.telegram_message_id !== null && (
        <span className="ml-1 text-xs text-slate-400">#{alerta.telegram_message_id}</span>
      )}
    </span>
  );
}

const VALIDADA: ReadonlySet<AlertValidationStatus> = new Set(["sostenida", "prometedora"]);

function ReglaCard({
  regla,
  onToggle,
  onDelete,
}: {
  regla: AlertRule;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const { config } = regla;
  return (
    <div
      className={`rounded border p-3 ${
        regla.enabled
          ? "border-slate-200 dark:border-slate-700"
          : "border-slate-200 opacity-60 dark:border-slate-800"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{regla.name}</span>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {regla.symbol} {regla.timeframe} · {regla.pattern_name} ·{" "}
              {regla.direction === "bullish" ? "LONG" : "SHORT"}
            </span>
            {!regla.enabled && (
              <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                pausada
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            SL {config.stop_loss_pct === null ? "sin stop" : `${config.stop_loss_pct} %`} · TP{" "}
            {config.take_profit_pct === null ? "sin objetivo" : `${config.take_profit_pct} %`} ·
            máx. {config.max_hold ?? "—"} velas
            {!config.base_known && (
              <span
                className="ml-2 text-xs text-amber-600 dark:text-amber-400"
                title="El informe es anterior a que se guardara la comisión, así que no se sabe con qué costes se simuló."
              >
                comisiones desconocidas
              </span>
            )}
          </p>
          <div className="mt-2 max-w-md">
            <ValidationBadge status={regla.validation_status} note={regla.validation_note} />
          </div>
          <div className="mt-1.5 space-y-0.5">
            <CoverageBadge coverage={regla.pattern_coverage} />
            {regla.backing_oi_low !== null && regla.backing_oi_high !== null && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                IC95% [{Number(regla.backing_oi_low).toFixed(1)} ;{" "}
                {Number(regla.backing_oi_high).toFixed(1)}]% · OOS{" "}
                {regla.backing_oos_return_pct !== null
                  ? `${Number(regla.backing_oos_return_pct).toFixed(1)}%`
                  : "—"}
                {regla.backing_windows !== null && ` · ${regla.backing_windows} ventanas`}
              </p>
            )}
            {regla.last_evaluation_note && (
              <p className="text-xs text-slate-400 dark:text-slate-500">
                Última evaluación: {regla.last_evaluation_note}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={onToggle}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            {regla.enabled ? "Pausar" : "Activar"}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50 dark:border-slate-600 dark:hover:bg-rose-950/40"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
