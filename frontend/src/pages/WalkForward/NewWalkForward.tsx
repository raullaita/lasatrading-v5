import { useEffect, useMemo, useState } from "react";

import { AlertTriangle, Loader2, Rocket } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { getBacktestAvailableScans } from "../../services/backtestsApi";
import { createWalkForward } from "../../services/walkForwardApi";
import { diasDeRango, estimarCoste } from "./coste";
import type { BacktestAvailableScan } from "../../types/backtesting";
import type { WalkForwardCreateIn } from "../../types/walkForward";
import { formatDateEs } from "../../utils/format";

/**
 * Formulario de nuevo walk-forward.
 *
 * La pantalla tiene una sola cosa que el backtest no tiene, y es el contador de
 * simulaciones. Un walk-forward no simula una vez: simula
 * `ventanas x combinaciones`, y el coste crece con el producto de las dos cosas.
 * Mostrar "N combinaciones x M ventanas = K simulaciones" **antes** de lanzar
 * es lo que evita que el usuario descubra a los cinco minutos que ha encolado
 * 1.800 simulaciones, y ademas es lo que exige la regla 4 del Contrato
 * Estadistico: el numero de combinaciones evaluadas se publica.
 *
 * Y hay una trampa que el contador tiene que sortear: **las ventanas no las sabe
 * el frontend**. Dependen del rango real de las velas del escaneo, que el
 * navegador no tiene. Asi que el contador es una estimacion calculada con el
 * rango declarado del escaneo, y va rotulado como tal. El numero exacto lo dice
 * el 422 del backend cuando se pasa del tope, y el que se guarda en el informe
 * es el del motor. Poner un numero exacto aqui seria mentir por un detalle de
 * la UI que el usuario no puede comprobar.
 */

/** Una casilla de la rejilla: un valor, o "sin nivel" cuando esta vacia. */
function RejillaCampo<T extends number | null>({
  label,
  valores,
  onChange,
  permiteNull,
}: {
  label: string;
  valores: T[];
  onChange: (next: T[]) => void;
  permiteNull: boolean;
}) {
  return (
    <fieldset>
      <legend className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {valores.map((valor, indice) => (
          <input
            key={indice}
            type="number"
            step="0.1"
            min="0.1"
            placeholder={permiteNull ? "sin nivel" : ""}
            value={valor === null ? "" : String(valor)}
            onChange={(event) => {
              const texto = event.target.value.trim();
              const siguiente = [...valores];
              // `max_holds` no admite null y esta es la razon de que el campo
              // sea generico: un `(number|null)[]` comun obligaria a castear en
              // cada llamada, que es donde se colaria un `null` sin querer.
              siguiente[indice] = (texto === "" ? null : Number(texto)) as T;
              onChange(siguiente);
            }}
            className="w-24 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
          />
        ))}
        <button
          type="button"
          onClick={() => onChange([...valores, (permiteNull ? null : 1) as T])}
          className="rounded border border-slate-300 px-2 py-1 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
        >
          + valor
        </button>
      </div>
    </fieldset>
  );
}

export default function NewWalkForward() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [scans, setScans] = useState<BacktestAvailableScan[]>([]);
  const [loadingScans, setLoadingScans] = useState(true);
  const [scansError, setScansError] = useState<string | null>(null);

  const [scanId, setScanId] = useState(params.get("scan_job_id") ?? "");
  const [takeProfit, setTakeProfit] = useState<(number | null)[]>([null, 1.0, 2.0]);
  const [stopLoss, setStopLoss] = useState<(number | null)[]>([1.0, 1.5, 2.0]);
  const [maxHolds, setMaxHolds] = useState<number[]>([12, 24]);

  const [windowDays, setWindowDays] = useState("365");
  const [oosDays, setOosDays] = useState("90");
  const [stepDays, setStepDays] = useState("90");
  const [minWindows, setMinWindows] = useState("3");
  const [minTrades, setMinTrades] = useState("30");
  const [holdoutDays, setHoldoutDays] = useState("0");
  const [beatsMarketRatio, setBeatsMarketRatio] = useState("0.6");
  const [regimesDeclared, setRegimesDeclared] = useState("1");
  const [maxSimulations, setMaxSimulations] = useState("2000");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getBacktestAvailableScans()
      .then((data) => {
        setScans(data);
        if (!scanId && data.length > 0) setScanId(data[0].id);
      })
      .catch((err: Error) => setScansError(err.message))
      .finally(() => setLoadingScans(false));
    // Solo al montar: despues el selector manda.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const escaneo = useMemo(() => scans.find((s) => s.id === scanId) ?? null, [scans, scanId]);

  /**
   * El contador. Se recalcula en cada cambio de la rejilla o de las ventanas, y
   * avisa en tres situaciones distintas, cada una con su color, porque no son el
   * mismo problema: Demasiado es un error de la peticion; pocas ventanas es un
   * dato del rango.
   */
  const conteo = useMemo(
    () =>
      estimarCoste({
        takeProfit,
        stopLoss,
        maxHolds,
        dias: escaneo ? diasDeRango(escaneo.date_from, escaneo.date_to) : 0,
        windowDays: Number(windowDays) || 0,
        oosDays: Number(oosDays) || 0,
        stepDays: Number(stepDays) || 1,
        holdoutDays: Number(holdoutDays) || 0,
      }),
    [takeProfit, stopLoss, maxHolds, escaneo, windowDays, oosDays, stepDays, holdoutDays],
  );

  const sePasaDelTope = conteo.simulaciones > (Number(maxSimulations) || 0);
  const sinVentanas = conteo.ventanas === 0;

  const lanzar = async () => {
    if (!scanId) {
      setError("Elige un escaneo");
      return;
    }
    setSubmitting(true);
    setError(null);
    const cuerpo: WalkForwardCreateIn = {
      scan_job_id: scanId,
      grid: {
        take_profit_pcts: takeProfit,
        stop_loss_pcts: stopLoss,
        max_holds: maxHolds,
      },
      window_days: Number(windowDays),
      oos_days: Number(oosDays),
      step_days: Number(stepDays),
      min_windows: Number(minWindows),
      min_trades: Number(minTrades),
      holdout_days: Number(holdoutDays),
      beats_market_ratio: Number(beatsMarketRatio),
      regimes_declared: Number(regimesDeclared),
      max_simulations: Number(maxSimulations),
    };
    try {
      const run = await createWalkForward(cuerpo);
      navigate(`/walk-forward/runs/${run.id}`);
    } catch (err) {
      // El 422 de simulaciones trae el total en el mensaje, y es el mensaje mas
      // util de esta pantalla: enseña el numero que hay que bajar. Se enseña tal
      // cual en vez de sustituirlo por "ha ocurrido un error".
      setError(err instanceof Error ? err.message : "No se pudo lanzar el walk-forward");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Nuevo walk-forward</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Parte el rango en ventanas, elige en cada una la mejor combinaci&oacute;n por Sharpe
          dentro de la parte de in-sample, y la mide en la parte que no ha visto. Al final no da un
          ganador: da candidatos con su veredicto.
        </p>
      </header>

      {scansError && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
          {scansError}
        </div>
      )}

      <section className="space-y-3 rounded border border-slate-200 p-4 dark:border-slate-700">
        <h2 className="font-medium">Escaneo</h2>
        {loadingScans ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <select
            value={scanId}
            onChange={(event) => setScanId(event.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
          >
            {scans.map((scan) => (
              <option key={scan.id} value={scan.id}>
                {scan.symbol} {scan.timeframe} · {formatDateEs(scan.date_from)} →{" "}
                {formatDateEs(scan.date_to)}
              </option>
            ))}
          </select>
        )}
        {escaneo && (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {conteo.dias} días de datos. Un rango corto no da ventanas: con menos de unos 60 días no
            sale ni una, y el motor lo avisa en vez de fingir un resultado.
          </p>
        )}
      </section>

      <section className="space-y-4 rounded border border-slate-200 p-4 dark:border-slate-700">
        <h2 className="font-medium">Rejilla</h2>
        <RejillaCampo
          label="Take profit (%) — vacío = sin take profit"
          valores={takeProfit}
          onChange={setTakeProfit}
          permiteNull
        />
        <RejillaCampo
          label="Stop loss (%) — vacío = sin stop loss"
          valores={stopLoss}
          onChange={setStopLoss}
          permiteNull
        />
        <RejillaCampo<number>
          label="Máximo de velas"
          valores={maxHolds}
          onChange={setMaxHolds}
          permiteNull={false}
        />
      </section>

      <section className="space-y-4 rounded border border-slate-200 p-4 dark:border-slate-700">
        <h2 className="font-medium">Ventanas y guardas</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm">
            In-sample (días)
            <input
              type="number"
              min="7"
              value={windowDays}
              onChange={(e) => setWindowDays(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Out-of-sample (días)
            <input
              type="number"
              min="7"
              value={oosDays}
              onChange={(e) => setOosDays(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Desplazamiento (días)
            <input
              type="number"
              min="1"
              value={stepDays}
              onChange={(e) => setStepDays(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Reserva final (días)
            <input
              type="number"
              min="0"
              value={holdoutDays}
              onChange={(e) => setHoldoutDays(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Ventanas mínimas
            <input
              type="number"
              min="1"
              value={minWindows}
              onChange={(e) => setMinWindows(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Operaciones mínimas
            <input
              type="number"
              min="0"
              value={minTrades}
              onChange={(e) => setMinTrades(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Ventanas que superan al mercado
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={beatsMarketRatio}
              onChange={(e) => setBeatsMarketRatio(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
          <label className="text-sm">
            Regímenes declarados
            <input
              type="number"
              min="1"
              max="12"
              value={regimesDeclared}
              onChange={(e) => setRegimesDeclared(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
        </div>
        <label className="block text-sm">
          Tope de simulaciones
          <input
            type="number"
            min="1"
            value={maxSimulations}
            onChange={(e) => setMaxSimulations(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 sm:w-48 dark:border-slate-600 dark:bg-slate-800"
          />
        </label>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Los reg&iacute;menes declarados no los detecta el motor: los dice el usuario. Con menos de
          tres el techo del veredicto es «prometedora» y la pantalla lo escribe, porque un dato que
          el motor no puede ver no puede decidirlo por su cuenta.
        </p>
      </section>

      <section
        className={`rounded border p-4 ${
          sePasaDelTope
            ? "border-red-400 bg-red-50 dark:border-red-800 dark:bg-red-950/40"
            : sinVentanas
              ? "border-amber-400 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40"
              : "border-slate-200 dark:border-slate-700"
        }`}
      >
        <h2 className="font-medium">Coste estimado</h2>
        <p className="mt-1 text-3xl font-semibold tabular-nums">
          {conteo.simulaciones.toLocaleString("es-ES")}
        </p>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {conteo.combinaciones} combinaciones ×{" "}
          <span title="Estimado con el rango declarado del escaneo; el motor cuenta sobre el rango real de las velas y puede diferir en una.">
            ~{conteo.ventanas} ventanas
          </span>{" "}
          = simulaciones
        </p>
        {sePasaDelTope && (
          <p className="mt-2 flex items-center gap-2 text-sm text-red-700 dark:text-red-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Pasa del tope de {Number(maxSimulations).toLocaleString("es-ES")}. Reduce la rejilla,
            agranda las ventanas o sube el tope.
          </p>
        )}
        {sinVentanas && !sePasaDelTope && (
          <p className="mt-2 flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Con estos tamaños no sale ni una ventana en este rango.
          </p>
        )}
      </section>

      {error && (
        <div
          role="alert"
          className="whitespace-pre-line rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={lanzar}
        disabled={submitting || !scanId || sePasaDelTope || sinVentanas}
        className="inline-flex items-center gap-2 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
        Ejecutar
      </button>
    </div>
  );
}
