import { useEffect, useMemo, useState } from "react";

import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Loader2 } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { DateRangePicker } from "../../components/DataImport/wizard/DateRangePicker";
import { PatternSelector } from "../../components/Patterns/PatternSelector";
import { missingFeatures } from "../../components/Patterns/patternUtils";
import { createPatternScan, getAvailableData, getPatternCatalog } from "../../services/patternsApi";
import type {
  PatternAvailableData,
  PatternDefinition,
  PatternScanConfig,
  PatternSelection,
} from "../../types/patterns";
import { formatDateEs } from "../../utils/format";

const STEPS = [
  { title: "Datos", description: "Selecciona el par a escanear y el rango de fechas" },
  { title: "Patrones", description: "Elige los patrones y ajusta sus parámetros" },
  { title: "Resumen", description: "Revisa la configuración e inicia el escaneo" },
];

/** ISO 8601 a `YYYY-MM-DD`, que es lo que espera `<input type="date">`. */
function toDateInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  // Se pasa por `toISOString` a proposito: el backend guarda y devuelve UTC, y
  // mezclar la zona local con UTC aqui desplaza el rango un dia en los bordes.
  return date.toISOString().slice(0, 10);
}

export default function NewPatternScan() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [step, setStep] = useState(0);

  const [availableData, setAvailableData] = useState<PatternAvailableData[]>([]);
  const [catalog, setCatalog] = useState<PatternDefinition[]>([]);
  const [loadingCatalog, setLoadingCatalog] = useState(true);

  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("1h");
  const [range, setRange] = useState({ from: "", to: "" });
  const [patterns, setPatterns] = useState<PatternSelection[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([getAvailableData(), getPatternCatalog()])
      .then(([data, definitions]) => {
        setAvailableData(data);
        setCatalog(definitions);
      })
      .catch(() => {
        setError("No se pudieron cargar los datos disponibles ni el catálogo de patrones.");
      })
      .finally(() => setLoadingCatalog(false));
  }, []);

  /**
   * Preselección desde la galería: `/patterns/new?pattern=MACD_CROSS_BULLISH`.
   *
   * Se aplica una sola vez, cuando el catálogo llega. Sin esta guarda, el
   * efecto se volvería a disparar cada vez que `catalog` cambia de referencia y
   * machacaría cualquier ajuste de parámetros hecho por el usuario.
   */
  const [preselectApplied, setPreselectApplied] = useState(false);
  useEffect(() => {
    if (preselectApplied || catalog.length === 0) return;
    setPreselectApplied(true);
    const requested = searchParams.get("pattern");
    if (!requested) return;
    const definition = catalog.find((d) => d.code === requested);
    if (!definition) return;
    const params: Record<string, number> = {};
    for (const spec of definition.params) params[spec.key] = spec.default;
    setPatterns([{ code: definition.code, params }]);
    // Si el patrón viene de la galería, casi siempre se quiere ir directos a
    // configurarlo: los datos se rellenan solos con el rango real de datos.
    setStep(1);
  }, [catalog, preselectApplied, searchParams]);

  /** El par elegido, con sus velas y features ya calculadas. */
  const pair = useMemo(
    () => availableData.find((d) => d.symbol === symbol && d.timeframe === timeframe) ?? null,
    [availableData, symbol, timeframe],
  );

  /**
   * Al elegir par, el rango se ajusta a los datos que existen de verdad.
   *
   * `first_candle`/`last_candle` vienen en `PatternAvailableData`: sin esto el
   * usuario acaba pidiendo un rango que llega hasta hoy sobre un símbolo que
   * se importó hace seis meses, y el escaneo sale con huecos o directamente
   * con un 400 por falta de velas.
   */
  useEffect(() => {
    if (!pair) return;
    const from = toDateInput(pair.first_candle);
    const to = toDateInput(pair.last_candle);
    if (from && to) setRange({ from, to });
  }, [pair]);

  const missing = useMemo(
    () => (pair ? missingFeatures(patterns, catalog, pair.indicators) : []),
    [patterns, catalog, pair],
  );

  const rangeValid = !!range.from && !!range.to && range.from < range.to;

  /**
   * `!!pair` aparece en los tres pasos a proposito.
   *
   * La galería entra por `?pattern=`, que deja el wizard en el paso 2 con los
   * patrones puestos pero sin símbolo. `missingFeatures` devuelve `[]` cuando no
   * hay par, porque no hay features que comparar, así que sin esta comprobación
   * el paso parecería válido: se llegaría al resumen y el envío construiría un
   * `date_from` con un `NaN` en medio y el backend respondería 400 con un error
   * incomprensible. Con `!!pair` el botón «Siguiente» no se activa hasta que el
   * usuario elija símbolo y rango.
   */
  const stepValid: boolean[] = [
    !!pair && rangeValid,
    !!pair && patterns.length > 0 && missing.length === 0,
    !!pair && patterns.length > 0 && missing.length === 0 && rangeValid,
  ];

  const isLast = step === STEPS.length - 1;

  const availableSymbols = useMemo(
    () => [...new Set(availableData.map((d) => d.symbol))].sort(),
    [availableData],
  );

  const timeframesForSymbol = useMemo(
    () =>
      availableData
        .filter((d) => d.symbol === symbol)
        .map((d) => d.timeframe)
        .sort(),
    [availableData, symbol],
  );

  const submit = async () => {
    if (!pair) return;
    const config: PatternScanConfig = {
      symbol,
      timeframe,
      date_from: new Date(`${range.from}T00:00:00`).toISOString(),
      date_to: new Date(`${range.to}T23:59:59.999`).toISOString(),
      patterns,
    };
    setSubmitting(true);
    setError(null);
    try {
      const result = await createPatternScan(config);
      navigate(`/patterns/scans/${result.id}`);
    } catch {
      setError("No se pudo iniciar el escaneo. Revisa los datos y los patrones seleccionados.");
      setSubmitting(false);
    }
  };

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-3xl">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
          Nuevo escaneo de patrones
        </h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">{STEPS[step].description}</p>

        <ol className="mb-8 flex items-center gap-2">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => i < step && setStep(i)}
                className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ${
                  i <= step
                    ? "bg-indigo-600 text-white"
                    : "border border-slate-300 bg-white text-slate-400 dark:border-slate-700 dark:bg-slate-900"
                }`}
              >
                {i + 1}
              </button>
              {i < STEPS.length - 1 && (
                <span
                  className={
                    i < step
                      ? "h-0.5 w-6 bg-indigo-600"
                      : "h-0.5 w-6 bg-slate-200 dark:bg-slate-800"
                  }
                />
              )}
            </li>
          ))}
        </ol>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {loadingCatalog ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Cargando catálogo y datos disponibles…
            </div>
          ) : (
            <>
              {step === 0 && (
                <div className="space-y-4">
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                      Símbolo
                    </span>
                    <select
                      value={symbol}
                      onChange={(e) => {
                        setSymbol(e.target.value);
                        setError(null);
                        // El timeframe puede quedar sin sentido para el simbolo
                        // nuevo: se vuelve al primero que exista.
                        const options = availableData
                          .filter((d) => d.symbol === e.target.value)
                          .map((d) => d.timeframe)
                          .sort();
                        if (options.length > 0 && !options.includes(timeframe)) {
                          setTimeframe(options[0]);
                        }
                      }}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    >
                      <option value="">Selecciona un símbolo</option>
                      {availableSymbols.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                      Timeframe
                    </span>
                    <select
                      value={timeframe}
                      onChange={(e) => {
                        setTimeframe(e.target.value);
                        setError(null);
                      }}
                      disabled={!symbol}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    >
                      {timeframesForSymbol.length === 0 && <option value="">—</option>}
                      {timeframesForSymbol.map((tf) => (
                        <option key={tf} value={tf}>
                          {tf}
                        </option>
                      ))}
                    </select>
                  </label>

                  {pair && (
                    <div className="rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800/50">
                      <p className="text-slate-600 dark:text-slate-300">
                        {pair.candles.toLocaleString("es-ES")} velas disponibles
                        {pair.first_candle && pair.last_candle && (
                          <>
                            {" "}
                            · {formatDateEs(pair.first_candle)} → {formatDateEs(pair.last_candle)}
                          </>
                        )}
                      </p>
                      {pair.indicators.length > 0 ? (
                        <p className="mt-1 flex flex-wrap gap-1">
                          {pair.indicators.map((feature) => (
                            <span
                              key={feature}
                              className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:bg-slate-700 dark:text-slate-300"
                            >
                              {feature}
                            </span>
                          ))}
                        </p>
                      ) : (
                        <p className="mt-1 text-amber-600 dark:text-amber-400">
                          Este par no tiene features calculadas: ningún patrón podrá ejecutarse.
                        </p>
                      )}
                    </div>
                  )}

                  <DateRangePicker value={range} onChange={setRange} />
                </div>
              )}

              {step === 1 && (
                <div className="space-y-4">
                  {!pair && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                      <p className="flex items-center gap-1.5 font-medium text-amber-800 dark:text-amber-300">
                        <AlertTriangle className="h-4 w-4 shrink-0" />
                        Falta elegir el par a escanear
                      </p>
                      <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                        El patrón viene preseleccionado desde la galería, pero el símbolo y el rango
                        siguen vacíos. Vuelve al paso 1 y selecciónalos para poder continuar.
                      </p>
                      <button
                        type="button"
                        onClick={() => setStep(0)}
                        className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100 dark:border-amber-800 dark:text-amber-200 dark:hover:bg-amber-900/50"
                      >
                        <ArrowLeft className="h-3.5 w-3.5" />
                        Ir a seleccionar datos
                      </button>
                    </div>
                  )}
                  <PatternSelector
                    patterns={patterns}
                    onChange={setPatterns}
                    catalog={catalog}
                    disabled={submitting}
                  />
                  {missing.length > 0 && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                      <p className="flex items-center gap-1.5 font-medium text-amber-800 dark:text-amber-300">
                        <AlertTriangle className="h-4 w-4 shrink-0" />
                        Faltan features para este par
                      </p>
                      <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                        {symbol} ({timeframe}) no tiene:{" "}
                        {missing.map((f) => (
                          <code key={f} className="mx-0.5 font-mono">
                            {f}
                          </code>
                        ))}
                        . Créalas en «Indicadores» y vuelve: encolar el escaneo ahora fallaría con{" "}
                        <code className="font-mono">MissingFeaturesError</code>.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {step === 2 && (
                <div className="space-y-3">
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    Resumen de la configuración
                  </h3>
                  <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-800/50">
                    <Row label="Símbolo" value={symbol} />
                    <Row label="Timeframe" value={timeframe} />
                    <Row
                      label="Período"
                      value={
                        rangeValid
                          ? `${formatDateEs(range.from)} → ${formatDateEs(range.to)}`
                          : "Sin rango válido"
                      }
                    />
                    <Row
                      label="Velas disponibles"
                      value={pair ? `${pair.candles.toLocaleString("es-ES")} disponibles` : "—"}
                    />
                    <Row
                      label="Patrones"
                      value={patterns.map((p) => p.code).join(", ") || "Ninguno"}
                    />
                  </div>

                  <ul className="space-y-1.5">
                    {patterns.map((p) => {
                      const definition = catalog.find((d) => d.code === p.code);
                      if (!definition) return null;
                      return (
                        <li
                          key={p.code}
                          className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800"
                        >
                          <span className="font-medium text-slate-700 dark:text-slate-200">
                            {definition.short_label}
                          </span>
                          <span className="ml-2 font-mono text-[10px] text-slate-400 dark:text-slate-500">
                            {definition.params
                              .map((spec) => `${spec.key}=${p.params[spec.key] ?? spec.default}`)
                              .join(", ")}
                          </span>
                        </li>
                      );
                    })}
                  </ul>

                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/40">
                    <p className="flex items-start gap-2 text-sm text-emerald-800 dark:text-emerald-300">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>
                        Listo para escanear <strong>{patterns.length}</strong> patrón
                        {patterns.length === 1 ? "" : "s"} en <strong>{symbol}</strong> ({timeframe}
                        ). El job se encolará y podrás seguir su progreso y sus logs en tiempo real.
                      </span>
                    </p>
                  </div>
                </div>
              )}
            </>
          )}

          <div className="mt-8 flex items-center justify-between border-t border-slate-100 pt-5 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              disabled={step === 0 || loadingCatalog}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              <ArrowLeft className="h-4 w-4" /> Anterior
            </button>
            {isLast ? (
              <button
                type="button"
                onClick={() => void submit()}
                disabled={submitting || !stepValid[step] || loadingCatalog}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowRight className="h-4 w-4" />
                )}
                Iniciar escaneo
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                disabled={!stepValid[step] || loadingCatalog}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                Siguiente
                <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </div>

          {error && (
            <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
              {error}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-xs text-slate-500 dark:text-slate-400">{label}</span>
      <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{value}</p>
    </div>
  );
}
