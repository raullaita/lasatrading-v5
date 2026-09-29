import { useEffect, useMemo, useState } from "react";

import { Loader2, Rocket } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  Field,
  PageHeader,
  PageShell,
  cardClass,
  errorClass,
  inputClass,
  primaryButtonClass,
} from "../../components/ui/PageShell";
import { getBacktestAvailableScans } from "../../services/backtestsApi";
import { createWalkForward } from "../../services/walkForwardApi";
import { daysFromRange, estimateCost } from "./coste";
import type { BacktestAvailableScan } from "../../types/backtesting";
import type { WalkForwardCreateIn } from "../../types/walkForward";
import { formatDateEs } from "../../utils/format";

/**
 * Formulario de nuevo walk-forward.
 *
 * La pantalla tiene una sola cosa que el backtest no tiene, y es el contador de
 * simulaciones. Un walk-forward no simula una vez: simula
 * `ventanas x combinaciones`, y el coste crece con el producto de las dos. Mostrar
 * "N combinaciones x M ventanas = K simulaciones" **antes** de lanzar es lo que
 * evita que el usuario descubra a los cinco minutos que ha encolado 1.800
 * simulaciones, y además es lo que exige la regla 4 del Contrato Estadístico: el
 * número de combinaciones evaluadas se publica.
 *
 * ## El contador no es un número exacto, y por eso lo dice
 *
 * **Las ventanas no las sabe el frontend**: dependen del rango real de las velas
 * del escaneo, que el navegador no tiene. El contador usa el rango *declarado* y
 * va rotulado como estimación. El número exacto lo dice el 422 del backend
 * cuando se pasa del tope, y el que queda en el informe es el del motor. Poner
 * un número exacto aquí sería mentir por un detalle de la UI que el usuario no
 * puede comprobar.
 */

/** Una casilla de la rejilla: un valor, o "sin nivel" cuando está vacía. */
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
    <Field label={label}>
      <div className="flex flex-wrap gap-2">
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
              // `max_holds` no admite null y esta es la razón de que el campo sea
              // genérico: un `(number|null)[]` común obligaría a castear en cada
              // llamada, que es donde se colaría un `null` sin querer.
              siguiente[indice] = (texto === "" ? null : Number(texto)) as T;
              onChange(siguiente);
            }}
            className={`${inputClass} w-24`}
          />
        ))}
        <button
          type="button"
          onClick={() => onChange([...valores, (permiteNull ? null : 1) as T])}
          className="rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          + valor
        </button>
      </div>
    </Field>
  );
}

export default function NewWalkForward() {
  const navegar = useNavigate();
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
    // Solo al montar: después manda el selector.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const escaneo = useMemo(
    () => scans.find((s) => s.id === scanId) ?? null,
    [scans, scanId],
  );

  /**
   * El contador. Se recalcula con cada cambio, y avisa en tres situaciones
   * distintas con tres estilos distintos, porque no son el mismo problema:
   * "demasiado" es un error de la petición; "pocas ventanas" es un dato del
   * rango.
   */
  const conteo = useMemo(
    () =>
      estimateCost({
        takeProfit,
        stopLoss,
        maxHolds,
        days: escaneo ? daysFromRange(escaneo.date_from, escaneo.date_to) : 0,
        windowDays: Number(windowDays) || 0,
        oosDays: Number(oosDays) || 0,
        stepDays: Number(stepDays) || 1,
        holdoutDays: Number(holdoutDays) || 0,
      }),
    [
      takeProfit,
      stopLoss,
      maxHolds,
      escaneo,
      windowDays,
      oosDays,
      stepDays,
      holdoutDays,
    ],
  );

  const sePasaDelTope = conteo.simulations > (Number(maxSimulations) || 0);
  const sinVentanas = conteo.windows === 0;

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
      navegar(`/walk-forward/runs/${run.id}`);
    } catch (err) {
      // El 422 de simulaciones trae el total en el mensaje, y es el mensaje más
      // útil de esta pantalla: enseña el número que hay que bajar. Se enseña tal
      // cual en vez de sustituirlo por "ha ocurrido un error".
      setError(
        err instanceof Error ? err.message : "No se pudo lanzar el walk-forward",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <PageShell>
      <PageHeader
        title="Nuevo walk-forward"
        subtitle="Parte el rango en ventanas, elige en cada una la mejor combinación por Sharpe dentro de la parte de in-sample, y la mide en la parte que no ha visto. Al final no da un ganador: da candidatos con su veredicto."
      />

      {scansError && <p className={errorClass}>{scansError}</p>}

      <section className={`${cardClass} mb-4 p-4`}>
        <h2 className="mb-3 font-semibold text-slate-900 dark:text-slate-100">
          Escaneo
        </h2>
        {loadingScans ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Field label="Escaneo completado">
            <select
              value={scanId}
              onChange={(event) => setScanId(event.target.value)}
              className={`${inputClass} w-full`}
            >
              {scans.map((scan) => (
                <option key={scan.id} value={scan.id}>
                  {scan.symbol} {scan.timeframe} · {formatDateEs(scan.date_from)} →{" "}
                  {formatDateEs(scan.date_to)}
                </option>
              ))}
            </select>
          </Field>
        )}
        {escaneo && (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {conteo.days} días de datos. Un rango corto no da ventanas: con menos de
            unos 60 días no sale ni una, y el motor lo avisa en vez de fingir un
            resultado.
          </p>
        )}
      </section>

      <section className={`${cardClass} mb-4 space-y-4 p-4`}>
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">Rejilla</h2>
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

      <section className={`${cardClass} mb-4 space-y-4 p-4`}>
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">
          Ventanas y guardas
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="In-sample (días)">
            <input
              type="number"
              min="7"
              value={windowDays}
              onChange={(e) => setWindowDays(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Out-of-sample (días)">
            <input
              type="number"
              min="7"
              value={oosDays}
              onChange={(e) => setOosDays(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Desplazamiento (días)">
            <input
              type="number"
              min="1"
              value={stepDays}
              onChange={(e) => setStepDays(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Reserva final (días)">
            <input
              type="number"
              min="0"
              value={holdoutDays}
              onChange={(e) => setHoldoutDays(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Ventanas mínimas">
            <input
              type="number"
              min="1"
              value={minWindows}
              onChange={(e) => setMinWindows(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Operaciones mínimas">
            <input
              type="number"
              min="0"
              value={minTrades}
              onChange={(e) => setMinTrades(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Ventanas que superan al mercado">
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={beatsMarketRatio}
              onChange={(e) => setBeatsMarketRatio(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
          <Field label="Regímenes declarados">
            <input
              type="number"
              min="1"
              max="12"
              value={regimesDeclared}
              onChange={(e) => setRegimesDeclared(e.target.value)}
              className={`${inputClass} w-full`}
            />
          </Field>
        </div>
        <Field label="Tope de simulaciones">
          <input
            type="number"
            min="1"
            value={maxSimulations}
            onChange={(e) => setMaxSimulations(e.target.value)}
            className={`${inputClass} w-full sm:w-48`}
          />
        </Field>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Los regímenes **declarados** no los detecta el motor: los dice el
          usuario. Con menos de tres el techo del veredicto es «prometedora» y la
          pantalla lo escribe, porque un dato que el motor no puede ver no puede
          decidirlo por su cuenta.
        </p>
      </section>

      <section
        className={`${cardClass} mb-4 p-4 ${
          sePasaDelTope
            ? "!border-rose-300 dark:!border-rose-800"
            : sinVentanas
              ? "!border-amber-300 dark:!border-amber-800"
              : ""
        }`}
      >
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">
          Coste estimado
        </h2>
        <p className="mt-1 text-3xl font-bold tabular-nums text-slate-900 dark:text-slate-100">
          {conteo.simulations.toLocaleString("es-ES")}
        </p>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {conteo.combinations} combinaciones ×{" "}
          <span
            title="Estimado con el rango declarado del escaneo; el motor cuenta sobre el rango real de las velas y puede diferir en una."
            className="underline decoration-dotted"
          >
            ~{conteo.windows} ventanas
          </span>{" "}
          = simulaciones
        </p>
        {sePasaDelTope && (
          <p className="mt-2 flex items-center gap-2 text-sm text-rose-600 dark:text-rose-400">
            Pasa del tope de {Number(maxSimulations).toLocaleString("es-ES")}. Reduce
            la rejilla, agranda las ventanas o sube el tope.
          </p>
        )}
        {sinVentanas && !sePasaDelTope && (
          <p className="mt-2 flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400">
            Con estos tamaños no sale ni una ventana en este rango.
          </p>
        )}
      </section>

      {error && <p className={`${errorClass} whitespace-pre-line`}>{error}</p>}

      <button
        type="button"
        onClick={() => void lanzar()}
        disabled={submitting || !scanId || sePasaDelTope || sinVentanas}
        className={primaryButtonClass}
      >
        {submitting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Rocket className="h-4 w-4" />
        )}
        Ejecutar
      </button>
    </PageShell>
  );
}
