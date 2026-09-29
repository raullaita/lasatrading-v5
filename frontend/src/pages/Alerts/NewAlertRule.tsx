import { useEffect, useMemo, useState } from "react";

import { Loader2, Save } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { CoverageBadge, ValidationBadge } from "../../components/Alerts/ValidationBadge";
import {
  Field,
  PageHeader,
  PageShell,
  cardClass,
  errorClass,
  inputClass,
  primaryButtonClass,
} from "../../components/ui/PageShell";
import { createAlertRule } from "../../services/alertsApi";
import { getWalkForwards } from "../../services/walkForwardApi";
import type { AlertRuleCreateIn } from "../../types/alerts";
import type { WalkForwardRun } from "../../types/walkForward";
import { formatDateEs } from "../../utils/format";

/**
 * Alta de una regla de alerta.
 *
 * El formulario **no tiene campos de TP, SL ni `max_hold`**, y su ausencia es la
 * decisión de diseño más importante de la pantalla. Si los admitiera, alguien
 * podría decir «respaldada por el informe X» y escribir otros niveles, y el aviso
 * llevaría las credenciales de un experimento y los números de otro. Aquí los
 * niveles salen del informe o no hay niveles.
 *
 * Y el informe es **opcional**. Con el enfoque de avisar en vez de bloquear, una
 * regla sin respaldo es legítima: nace como `sin_evaluar` y su aviso sale con un
 * candil blanco que lo dice. La casilla de «sin informe» es el estado honesto, no
 * un error de configuración.
 */

/** Los patrones del catálogo con su dirección declarada.
 *
 *  La dirección la declara el catálogo, no la pantalla: por eso el selector de
 *  dirección **no** existe aquí. Si se dejara elegir, el backend la rechazaría al
 *  revés, y una casilla que solo puede mandar la respuesta incorrecta es una
 *  casilla que sobra.
 */
const PATRONES = [
  { code: "MACD_CROSS_BULLISH", dir: "bullish", nombre: "Cruce MACD alcista" },
  { code: "MACD_CROSS_BEARISH", dir: "bearish", nombre: "Cruce MACD bajista" },
  { code: "RSI_EXIT_OVERSOLD", dir: "bullish", nombre: "RSI sobreventa" },
  { code: "RSI_EXIT_OVERBOUGHT", dir: "bearish", nombre: "RSI sobrecompra" },
  { code: "MA_CROSS_BEARISH", dir: "bearish", nombre: "Cruce de medias bajista" },
  { code: "ENGULFING_BULLISH", dir: "bullish", nombre: "Envolvente alcista" },
  { code: "ENGULFING_BEARISH", dir: "bearish", nombre: "Envolvente bajista" },
] as const;

export default function NewAlertRule() {
  const navegar = useNavigate();

  const [informes, setInformes] = useState<WalkForwardRun[]>([]);
  const [cargando, setCargando] = useState(true);
  const [nombre, setNombre] = useState("");
  const [patron, setPatron] = useState<string>("MACD_CROSS_BULLISH");
  const [informeId, setInformeId] = useState("");
  const [candidata, setCandidata] = useState("1");
  const [sinRespaldo, setSinRespaldo] = useState(true);
  const [simbolo, setSimbolo] = useState("BTCUSDT");
  const [marco, setMarco] = useState("1h");
  const [enfriamiento, setEnfriamiento] = useState(60);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getWalkForwards(1, 50)
      .then((d) => {
        const completados = d.runs.filter((r) => r.status === "completed");
        setInformes(completados);
        const primero = completados[0];
        if (primero) {
          setInformeId(primero.id);
          setSimbolo(primero.config.symbol);
          setMarco(primero.config.timeframe);
        }
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false));
  }, []);

  const definicion = useMemo(
    () => PATRONES.find((p) => p.code === patron) ?? PATRONES[0],
    [patron],
  );

  const guardar = async () => {
    if (!nombre.trim()) {
      setError("La regla necesita un nombre");
      return;
    }
    setEnviando(true);
    setError(null);
    const cuerpo: AlertRuleCreateIn = {
      name: nombre.trim(),
      pattern_name: patron,
      direction: definicion.dir,
      cooldown_minutes: enfriamiento,
      walk_forward_run_id: sinRespaldo ? null : informeId || null,
      candidate_rank: sinRespaldo ? null : Number(candidata) || null,
      symbol: sinRespaldo ? simbolo : null,
      timeframe: sinRespaldo ? marco : null,
    };
    try {
      const regla = await createAlertRule(cuerpo);
      navegar(`/alerts?creada=${regla.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear la regla");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <PageShell>
      <PageHeader
        title="Nueva regla de alerta"
        subtitle="Una regla vigila un patrón y avisa cuando aparece. Los niveles de la operación no se escriben aquí: salen del informe que la respalda, o no los hay."
      />

      {error && <p className={`${errorClass} whitespace-pre-line`}>{error}</p>}

      <section className={`${cardClass} mb-4 space-y-4 p-4`}>
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">
          Qué vigilar
        </h2>
        <Field label="Nombre">
          <input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="BTC MACD, el de la calibración"
            className={`${inputClass} w-full`}
          />
        </Field>
        <Field label="Patrón">
          <select
            value={patron}
            onChange={(e) => setPatron(e.target.value)}
            className={`${inputClass} w-full`}
          >
            {PATRONES.map((p) => (
              <option key={p.code} value={p.code}>
                {p.nombre}
              </option>
            ))}
          </select>
        </Field>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          La dirección ({definicion.dir === "bullish" ? "LONG" : "SHORT"}) la
          declara el catálogo y sigue al patrón: el backend rechaza la contraria,
          porque un aviso con la dirección invertida es un aviso al revés. Por eso
          aquí no hay selector de dirección.
        </p>
        <Field label="Enfriamiento entre avisos (minutos)">
          <input
            type="number"
            min="0"
            value={enfriamiento}
            onChange={(e) => setEnfriamiento(Number(e.target.value))}
            className={`${inputClass} w-40`}
          />
        </Field>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Un patrón puede disparar cada pocas velas. Quien recibe cuarenta mensajes
          en una hora apaga el sistema y no vuelve a encenderlo.
        </p>
      </section>

      <section className={`${cardClass} mb-4 space-y-4 p-4`}>
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">Respaldo</h2>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            checked={sinRespaldo}
            onChange={(e) => setSinRespaldo(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          Vigilar sin informe de respaldo
        </label>

        {sinRespaldo ? (
          <>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/40">
              <ValidationBadge status="sin_evaluar" />
              <p className="mt-2 text-sm text-amber-800 dark:text-amber-300">
                La regla nacerá como <strong>sin respaldo</strong> y su aviso saldrá
                con un candil blanco. Es un estado legítimo, no un error: la
                herramienta te da la información y{" "}
                <strong>la decisión de operar es tuya</strong>.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Símbolo">
                <input
                  value={simbolo}
                  onChange={(e) => setSimbolo(e.target.value)}
                  className={`${inputClass} w-full`}
                />
              </Field>
              <Field label="Timeframe">
                <select
                  value={marco}
                  onChange={(e) => setMarco(e.target.value)}
                  className={`${inputClass} w-full`}
                >
                  {["15m", "1h", "4h", "1d"].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Informe de walk-forward">
                <select
                  value={informeId}
                  onChange={(e) => setInformeId(e.target.value)}
                  disabled={cargando}
                  className={`${inputClass} w-full`}
                >
                  {cargando && <option>Cargando…</option>}
                  {informes.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.config.symbol} {r.config.timeframe} ·{" "}
                      {formatDateEs(r.created_at)} · {r.windows} ventanas
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Candidata nº">
                <input
                  type="number"
                  min="1"
                  value={candidata}
                  onChange={(e) => setCandidata(e.target.value)}
                  className={`${inputClass} w-full`}
                />
              </Field>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-800/50">
              <p className="text-slate-700 dark:text-slate-300">
                La regla se creará <strong>aunque la candidata esté descartada</strong>.
                Lo que hace el backend es etiquetarla y llevar el motivo al mensaje,
                no impedírla.
              </p>
              <p className="mt-2 text-slate-600 dark:text-slate-400">
                Y si el patrón no estaba en el filtro del informe, lo dirá con un
                candil de aviso: esos niveles no se simularon con ese patrón.
              </p>
              <div className="mt-1">
                <CoverageBadge coverage="fuera_de_filtro" />
              </div>
            </div>
          </>
        )}
      </section>

      <button
        type="button"
        onClick={() => void guardar()}
        disabled={enviando || !nombre.trim()}
        className={primaryButtonClass}
      >
        {enviando ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Save className="h-4 w-4" />
        )}
        Crear regla
      </button>
    </PageShell>
  );
}
