import { useEffect, useState } from "react";

import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { DateRangePicker } from "../../components/DataImport/wizard/DateRangePicker";
import { IndicatorSelector } from "../../components/Features/IndicatorSelector";
import { createFeatureJob, getAvailableData } from "../../services/featuresApi";
import type { FeatureJobConfig, IndicatorConfig } from "../../types/features";
import { formatDateEs } from "../../utils/format";

const STEPS = [
  { title: "Datos", description: "Selecciona el símbolo, timeframe y rango de fechas" },
  { title: "Indicadores", description: "Elige los indicadores técnicos y sus parámetros" },
  { title: "Resumen", description: "Revisa la configuración antes de confirmar" },
  { title: "Confirmación", description: "Inicia el cálculo de indicadores" },
];

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];

export default function NewFeatureJob() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [availableData, setAvailableData] = useState<{ symbol: string; timeframe: string }[]>([]);
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("1h");
  const [range, setRange] = useState({ from: "", to: "" });
  const [indicators, setIndicators] = useState<IndicatorConfig[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getAvailableData()
      .then(setAvailableData)
      .catch(() => setAvailableData([]));
  }, []);

  const availableSymbols = [...new Set(availableData.map((d) => d.symbol))].sort();

  const stepValid: boolean[] = [
    !!symbol && !!timeframe,
    !!(range.from && range.to && range.from < range.to),
    indicators.length > 0,
    true,
  ];

  const isLast = step === STEPS.length - 1;

  const submit = async () => {
    const config: FeatureJobConfig = {
      symbol,
      timeframe,
      date_from: new Date(`${range.from}T00:00:00`).toISOString(),
      date_to: new Date(`${range.to}T23:59:59.999`).toISOString(),
      indicators,
    };
    setSubmitting(true);
    setError(null);
    try {
      const result = await createFeatureJob(config);
      navigate(`/features/${result.id}`);
    } catch {
      setError("No se pudo iniciar el cálculo de indicadores.");
      setSubmitting(false);
    }
  };

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-2xl">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
          Nuevo cálculo de indicadores
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
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                >
                  {TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>
                      {tf}
                    </option>
                  ))}
                </select>
              </label>
              <DateRangePicker value={range} onChange={setRange} />
            </div>
          )}

          {step === 1 && <IndicatorSelector indicators={indicators} onChange={setIndicators} />}

          {step === 2 && (
            <div className="space-y-3">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Resumen de la configuración
              </h3>
              <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-800/50">
                <div>
                  <span className="text-xs text-slate-500 dark:text-slate-400">Símbolo</span>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{symbol}</p>
                </div>
                <div>
                  <span className="text-xs text-slate-500 dark:text-slate-400">Timeframe</span>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    {timeframe}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-slate-500 dark:text-slate-400">Período</span>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    {range.from && range.to
                      ? `${formatDateEs(range.from)} → ${formatDateEs(range.to)}`
                      : "Sin rango"}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-slate-500 dark:text-slate-400">Indicadores</span>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    {indicators.map((i) => i.name).join(", ") || "Ninguno"}
                  </p>
                </div>
              </div>
              <p className="text-xs text-slate-400 dark:text-slate-500">
                Tiempo estimado: ~{Math.max(1, Math.ceil(indicators.length * 2))}s por{" "}
                {indicators.length} indicador(es).
              </p>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Confirmar cálculo
              </h3>
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/40">
                <p className="text-sm text-emerald-800 dark:text-emerald-300">
                  ¿Estás seguro de iniciar el cálculo de {indicators.length} indicador(es) para{" "}
                  <strong>{symbol}</strong> ({timeframe}) entre{" "}
                  <strong>{formatDateEs(range.from)}</strong> y{" "}
                  <strong>{formatDateEs(range.to)}</strong>?
                </p>
              </div>
            </div>
          )}

          <div className="mt-8 flex items-center justify-between border-t border-slate-100 pt-5 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              disabled={step === 0}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              <ArrowLeft className="h-4 w-4" /> Anterior
            </button>
            {isLast ? (
              <button
                type="button"
                onClick={() => void submit()}
                disabled={submitting || !stepValid[step]}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowRight className="h-4 w-4" />
                )}
                Iniciar cálculo
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                disabled={!stepValid[step]}
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
