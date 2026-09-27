import { useEffect, useState } from "react";

import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  DateRangePicker,
  type DateRange,
} from "../../components/DataImport/wizard/DateRangePicker";
import { ImportOptions } from "../../components/DataImport/wizard/ImportOptions";
import { ImportSummary } from "../../components/DataImport/wizard/ImportSummary";
import { SymbolSelector } from "../../components/DataImport/wizard/SymbolSelector";
import { TimeframeSelector } from "../../components/DataImport/wizard/TimeframeSelector";
import { getSymbols, startImport } from "../../services/api";
import type { BinanceSymbol, ImportConfig, ImportMode } from "../../types/dataImport";

const STEPS = [
  { title: "Símbolos", description: "Selecciona los pares a importar" },
  { title: "Timeframes", description: "Elige las velas (1h, 4h, 1d…)" },
  { title: "Fechas", description: "Rango de fechas del historial" },
  { title: "Opciones", description: "Estrategia de importación" },
  { title: "Resumen", description: "Revisa y confirma" },
];

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

function toInputDate(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function todayInput(): string {
  return toInputDate(new Date());
}

function daysAgoInput(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toInputDate(d);
}

export default function NewImport() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [available, setAvailable] = useState<BinanceSymbol[]>([]);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [timeframes, setTimeframes] = useState<string[]>(["1h", "4h", "1d"]);
  const [range, setRange] = useState<DateRange>({
    from: daysAgoInput(365),
    to: todayInput(),
  });
  const [mode, setMode] = useState<ImportMode>("merge");
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    void getSymbols()
      .then(setAvailable)
      .catch(() => setAvailable([]));
  }, []);

  const stepValid: boolean[] = [
    symbols.length > 0,
    timeframes.length > 0,
    range.from < range.to,
    true,
    true,
  ];

  const toggleSymbol = (sym: string) => {
    setSymbols((prev) => (prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]));
  };

  const totalCombinations = symbols.length * timeframes.length;
  const canNext = stepValid[step];
  const isLast = step === STEPS.length - 1;

  const submit = async () => {
    const config: ImportConfig = {
      symbols,
      timeframes,
      date_from: new Date(`${range.from}T00:00:00`).toISOString(),
      date_to: new Date(`${range.to}T23:59:59.999`).toISOString(),
      import_mode: mode,
    };
    setSubmitting(true);
    setStatusMessage(null);
    try {
      const { job_id } = await startImport(config);
      navigate(`/import/${job_id}`);
    } catch {
      setStatusMessage("No se pudo iniciar la importación.");
      setSubmitting(false);
    }
  };

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-2xl">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Nueva importación</h1>
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
            <SymbolSelector available={available} selected={symbols} onToggle={toggleSymbol} />
          )}
          {step === 1 && <TimeframeSelector selected={timeframes} onChange={setTimeframes} />}
          {step === 2 && <DateRangePicker value={range} onChange={setRange} />}
          {step === 3 && <ImportOptions value={mode} onChange={setMode} />}
          {step === 4 && (
            <ImportSummary
              config={{
                symbols,
                timeframes,
                date_from: range.from,
                date_to: range.to,
                import_mode: mode,
              }}
              combinations={totalCombinations}
            />
          )}

          <div className="mt-8 flex items-center justify-between border-t border-slate-100 pt-5 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              disabled={step === 0}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              <ArrowLeft className="h-4 w-4" />
              Anterior
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
                Iniciar importación
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                disabled={!canNext}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                Siguiente
                <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </div>
          {statusMessage && (
            <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
              {statusMessage}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
