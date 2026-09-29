import { useEffect, useMemo, useState } from "react";

import { AlertTriangle, Loader2, Save } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { CoverageBadge, ValidationBadge } from "../../components/Alerts/ValidationBadge";
import { createAlertRule } from "../../services/alertsApi";
import { getWalkForwards } from "../../services/walkForwardApi";
import type { WalkForwardRun } from "../../types/walkForward";
import type { AlertRuleCreateIn } from "../../types/alerts";
import { formatDateEs } from "../../utils/format";

/**
 * Alta de una regla de alerta.
 *
 * El formulario **no tiene campos de TP, SL ni `max_hold`**, y su ausencia es la
 * decisión de diseño más importante de la pantalla. Si los admitiera, alguien
 * podría decir «respaldada por el informe X» y escribir otros niveles, y el
 * aviso llevaría las credenciales de un experimento y los números de otro. Aquí
 * los niveles salen del informe o no hay niveles.
 *
 * Y el informe es **opcional**. Con el enfoque de avisar en vez de bloquear, una
 * regla sin respaldo es legítima: nace como `sin_evaluar` y su aviso sale con un
 * candil blanco que lo dice. La casilla de «sin respaldo» es el estado honesto,
 * no un error de configuración.
 */
export default function NewAlertRule() {
  const navegar = useNavigate();

  const [informes, setInformes] = useState<WalkForwardRun[]>([]);
  const [cargando, setCargando] = useState(true);
  const [nombre, setNombre] = useState("");
  const [patron, setPatron] = useState("MACD_CROSS_BULLISH");
  const [direccion, setDireccion] = useState<"bullish" | "bearish">("bullish");
  const [informeId, setInformeId] = useState("");
  const [candidata, setCandidata] = useState("");
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

  // Los patrones del catálogo con su dirección declarada. La dirección la elige
  // el patrón, no la pantalla: por eso el selector de dirección desaparece cuando
  // el catálogo ya la dice, y el backend la rechaza si se manda al revés.
  const patrones = useMemo(
    () => [
      { code: "MACD_CROSS_BULLISH", dir: "bullish" as const, nombre: "Cruce MACD alcista" },
      { code: "MACD_CROSS_BEARISH", dir: "bearish" as const, nombre: "Cruce MACD bajista" },
      { code: "RSI_EXIT_OVERSOLD", dir: "bullish" as const, nombre: "RSI sobreventa" },
      { code: "RSI_EXIT_OVERBOUGHT", dir: "bearish" as const, nombre: "RSI sobrecompra" },
      { code: "MA_CROSS_BEARISH", dir: "bearish" as const, nombre: "Cruce de medias bajista" },
      { code: "ENGULFING_BULLISH", dir: "bullish" as const, nombre: "Envolvente alcista" },
      { code: "ENGULFING_BEARISH", dir: "bearish" as const, nombre: "Envolvente bajista" },
    ],
    [],
  );

  const alCambiarPatron = (codigo: string) => {
    setPatron(codigo);
    const definicion = patrones.find((p) => p.code === codigo);
    if (definicion) setDireccion(definicion.dir);
  };

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
      direction: direccion,
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
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Nueva regla de alerta</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Una regla vigila un patrón y avisa cuando aparece. Los niveles de la operación no se
          escriben aquí: salen del informe que la respalda, o no los hay.
        </p>
      </header>

      {error && (
        <div
          role="alert"
          className="whitespace-pre-line rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </div>
      )}

      <section className="space-y-3 rounded border border-slate-200 p-4 dark:border-slate-700">
        <h2 className="font-medium">Qué vigilar</h2>
        <label className="block text-sm">
          Nombre
          <input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="BTC MACD, el de la calibración"
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
          />
        </label>
        <label className="block text-sm">
          Patrón
          <select
            value={patron}
            onChange={(e) => alCambiarPatron(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
          >
            {patrones.map((p) => (
              <option key={p.code} value={p.code}>
                {p.nombre}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          La dirección ({direccion === "bullish" ? "LONG" : "SHORT"}) la declara el catálogo y sigue
          al patrón: el backend rechaza la contraria, porque un aviso con la dirección invertida es
          un aviso al revés.
        </p>
        <label className="block text-sm">
          Enfriamiento entre avisos (minutos)
          <input
            type="number"
            min="0"
            value={enfriamiento}
            onChange={(e) => setEnfriamiento(Number(e.target.value))}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 sm:w-40 dark:border-slate-600 dark:bg-slate-800"
          />
          <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
            Un patrón puede disparar cada pocas velas. Quien recibe cuarenta mensajes en una hora
            apaga el sistema y no vuelve a encenderlo.
          </span>
        </label>
      </section>

      <section className="space-y-3 rounded border border-slate-200 p-4 dark:border-slate-700">
        <h2 className="font-medium">Respaldo</h2>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={sinRespaldo}
            onChange={(e) => setSinRespaldo(e.target.checked)}
          />
          Vigilar sin informe de respaldo
        </label>

        {sinRespaldo ? (
          <>
            <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
              <ValidationBadge status="sin_evaluar" />
              <p className="mt-2">
                La regla nacerá como <strong>sin respaldo</strong> y su aviso saldrá con un candil
                blanco y un icono de aviso. Es un estado legítimo, no un error: la herramienta te da
                la información y <strong>la decisión de operar es tuya</strong>.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm">
                Símbolo
                <input
                  value={simbolo}
                  onChange={(e) => setSimbolo(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
                />
              </label>
              <label className="text-sm">
                Timeframe
                <select
                  value={marco}
                  onChange={(e) => setMarco(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
                >
                  {["15m", "1h", "4h", "1d"].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              Informe de walk-forward
              <select
                value={informeId}
                onChange={(e) => setInformeId(e.target.value)}
                disabled={cargando}
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800"
              >
                {cargando && <option>Cargando…</option>}
                {informes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.config.symbol} {r.config.timeframe} · {formatDateEs(r.created_at)} ·{" "}
                    {r.windows} ventanas
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Candidata nº
              <input
                type="number"
                min="1"
                value={candidata}
                onChange={(e) => setCandidata(e.target.value)}
                placeholder="1"
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
              />
            </label>
          </div>
        )}
        {!sinRespaldo && (
          <p className="flex items-start gap-2 text-xs text-slate-500 dark:text-slate-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            La regla se creará <strong>aunque la candidata esté descartada</strong>. Lo que hace el
            backend es etiquetarla y llevar el motivo al mensaje, no impedírla. Si el patrón no
            estaba en el filtro del informe, lo dirá con un candil de aviso: esos niveles no se
            simularon con ese patrón.
            <CoverageBadge coverage="fuera_de_filtro" />
          </p>
        )}
      </section>

      <button
        type="button"
        onClick={() => void guardar()}
        disabled={enviando || !nombre.trim()}
        className="inline-flex items-center gap-2 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        Crear regla
      </button>
    </div>
  );
}
