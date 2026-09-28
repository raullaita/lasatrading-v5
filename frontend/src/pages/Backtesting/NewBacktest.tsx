import { useEffect, useMemo, useState } from "react";

import { Loader2, Rocket } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { createBacktest, getBacktestAvailableScans } from "../../services/backtestsApi";
import { getPatternScan } from "../../services/patternsApi";
import type { BacktestAvailableScan, SignalDirection } from "../../types/backtesting";
import { formatDateEs } from "../../utils/format";

/**
 * Formulario de nuevo backtest.
 *
 * No hay ventana de rango: el rango lo hereda el escaneo elegido. Por eso el
 * primer paso es elegir un escaneo completado (`GET /available-scans`), y a
 * partir de ahi solo se configuran los parametros de la estrategia y,
 * opcionalmente, se filtran los patrones y direcciones que se simulan.
 *
 * `take_profit_pct` y `stop_loss_pct` se dejan vacios para no fijar objetivo:
 * el motor simula con el que exista. El backend rechaza una lista vacia en los
 * filtros (422), asi que "ninguno marcado" se manda como `null` = sin filtro.
 *
 * Acepta parametros por query string para que la tabla del barrido pueda
 * "Probar" una combinacion: el escaneo, el TP, el SL y las velas maxima llegan
 * puestos desde el run que se estaba calibrando, y el usuario solo tiene que
 * darle a lanzar. Sin esto habria que volver a elegir el escaneo y teclear los
 * numeros uno por uno, que es justo el trabajo que la calibracion evita.
 */
export default function NewBacktest() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  /**
   * Parametro de la URL como texto de campo. Un `null` explicito ("sin take
   * profit") llega como la cadena vacia, y vacio en un campo numerico es
   * justamente lo que el motor interpreta como "sin este nivel": los dos
   * sentidos de la ausencia seddddan bien sin mirar nada mas.
   */
  const desdeUrl = (clave: string, porDefecto: string): string => {
    const valor = params.get(clave);
    return valor === null ? porDefecto : valor;
  };
  const [scans, setScans] = useState<BacktestAvailableScan[]>([]);
  const [loadingScans, setLoadingScans] = useState(true);
  const [scansError, setScansError] = useState<string | null>(null);

  const [scanId, setScanId] = useState(params.get("scan_job_id") ?? "");
  const [scanPatternCodes, setScanPatternCodes] = useState<string[]>([]);
  const [scanLoading, setScanLoading] = useState(false);

  const [tp, setTp] = useState(desdeUrl("take_profit_pct", "2.0"));
  const [sl, setSl] = useState(desdeUrl("stop_loss_pct", "1.0"));
  const [maxHold, setMaxHold] = useState(desdeUrl("max_hold", "24"));
  const [feeBps, setFeeBps] = useState("4.0");
  const [capital, setCapital] = useState("1000");
  const [fraction, setFraction] = useState("1.0");
  const [allowShort, setAllowShort] = useState(true);

  /** Patrones marcados (filtro). Se rellena con todos los del escaneo. */
  const [patternSet, setPatternSet] = useState<Set<string>>(new Set());
  /** Direcciones marcadas (filtro). Vacio = simular ambas. */
  const [directionSet, setDirectionSet] = useState<Set<SignalDirection>>(new Set());

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getBacktestAvailableScans()
      .then((data) => {
        setScans(data);
        setLoadingScans(false);
      })
      .catch(() => {
        setScansError("No se pudieron cargar los escaneos disponibles.");
        setLoadingScans(false);
      });
  }, []);

  /**
   * Al elegir escaneo se pide el job completo para conocer sus patrones.
   * `available-scans` no los trae: solo simbolo, timeframe, rango y conteo.
   */
  useEffect(() => {
    setPatternSet(new Set());
    if (!scanId) {
      setScanPatternCodes([]);
      return;
    }
    setScanLoading(true);
    void getPatternScan(scanId)
      .then((job) => {
        const codes = job.patterns_config.map((p) => p.code);
        setScanPatternCodes(codes);
        setPatternSet(new Set(codes));
        setScanLoading(false);
      })
      .catch(() => {
        // Sin el job no se puede filtrar por patrones, pero el run si se puede
        // crear: el filtro simplemente no se envia.
        setScanPatternCodes([]);
        setScanLoading(false);
      });
  }, [scanId]);

  const selected = useMemo(() => scans.find((s) => s.id === scanId) ?? null, [scans, scanId]);

  const tpNum = tp === "" ? null : Number(tp);
  const slNum = sl === "" ? null : Number(sl);
  const strategyValid = Number.isFinite(Number(maxHold)) && Number(maxHold) >= 1;

  /**
   * «Todos marcados» no es un filtro: el backend trata `null` con el mismo
   * resultado y enviar la lista entera no aporta nada. Solo se manda el set
   * cuando deja de cubrir todo el escaneo.
   */
  const allPatternsMarked =
    scanPatternCodes.length > 0 && scanPatternCodes.every((c) => patternSet.has(c));
  const patternsFilter = patternSet.size === 0 || allPatternsMarked ? null : [...patternSet];
  const directionsFilter = directionSet.size === 0 ? null : [...directionSet];

  const submit = async () => {
    if (!strategyValid || !selected) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createBacktest({
        scan_job_id: scanId,
        strategy: {
          take_profit_pct: tpNum,
          stop_loss_pct: slNum,
          max_hold: Number(maxHold),
          fee_bps: Number(feeBps),
          initial_capital: Number(capital),
          use_fraction: Number(fraction),
          allow_short: allowShort,
        },
        patterns: patternsFilter,
        directions: directionsFilter,
      });
      navigate(`/backtesting/runs/${result.id}`);
    } catch {
      setError("No se pudo iniciar el backtest.");
      setSubmitting(false);
    }
  };

  const canSubmit = !!scanId && !!selected && strategyValid && !scanLoading;

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-2xl">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Nuevo backtest</h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          Simula una estrategia sobre las señales de un escaneo ya completado.
        </p>

        {error && (
          <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            {error}
          </p>
        )}

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-100">
            1 · Escaneo
          </h2>
          {loadingScans ? (
            <p className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin text-indigo-600" /> Cargando escaneos…
            </p>
          ) : scansError ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
              {scansError}
            </p>
          ) : scans.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
              No hay escaneos completados.{" "}
              <Link to="/patterns/new" className="text-indigo-600 underline dark:text-indigo-400">
                Crea uno en Detección de Patrones
              </Link>{" "}
              y vuelve aqui.
            </p>
          ) : (
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Escaneo a simular
              </span>
              <select
                value={scanId}
                onChange={(e) => setScanId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              >
                <option value="">Selecciona un escaneo</option>
                {scans.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.symbol} · {s.timeframe} · {formatDateEs(s.date_from)} →{" "}
                    {formatDateEs(s.date_to)} · {s.total_occurrences} señales
                  </option>
                ))}
              </select>
            </label>
          )}
          {selected && (
            <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
              {selected.total_candles.toLocaleString("es-ES")} velas ·{" "}
              {selected.total_occurrences.toLocaleString("es-ES")} señales
              {scanLoading ? " · cargando patrones…" : ` · ${scanPatternCodes.length} patrón(es)`}
            </p>
          )}
        </div>

        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-100">
            2 · Estrategia
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Take profit (%, vacío = sin objetivo)
              </span>
              <input
                type="number"
                step="0.1"
                min="0"
                value={tp}
                onChange={(e) => setTp(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Stop loss (%, vacío = sin stop)
              </span>
              <input
                type="number"
                step="0.1"
                min="0"
                value={sl}
                onChange={(e) => setSl(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Velas máximas en posición
              </span>
              <input
                type="number"
                min="1"
                step="1"
                value={maxHold}
                onChange={(e) => setMaxHold(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Comisión (puntos básicos)
              </span>
              <input
                type="number"
                step="0.1"
                min="0"
                value={feeBps}
                onChange={(e) => setFeeBps(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Capital inicial (USDT)
              </span>
              <input
                type="number"
                min="0"
                step="100"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Fracción del capital por operación (0-1)
              </span>
              <input
                type="number"
                step="0.05"
                min="0.01"
                max="1"
                value={fraction}
                onChange={(e) => setFraction(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
          </div>
          <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={allowShort}
              onChange={(e) => setAllowShort(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            Permitir posiciones cortas sobre señales bearish
          </label>
        </div>

        {selected && scanPatternCodes.length > 0 && (
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
              3 · Filtros <span className="text-sm font-normal text-slate-400">(opcional)</span>
            </h2>
            <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
              Dejar todo marcado equivale a simular sin filtro. Desmarcar todos los patrones
              también: el backend rechaza una lista vacía.
            </p>
            <div className="mb-4">
              <p className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
                Patrones
              </p>
              <div className="flex flex-wrap gap-2">
                {scanPatternCodes.map((code) => (
                  <label
                    key={code}
                    className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 dark:border-slate-700 dark:text-slate-300"
                  >
                    <input
                      type="checkbox"
                      checked={patternSet.has(code)}
                      onChange={(e) =>
                        setPatternSet((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(code);
                          else next.delete(code);
                          return next;
                        })
                      }
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    {code}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
                Direcciones
              </p>
              <div className="flex flex-wrap gap-2">
                {(["bullish", "bearish"] as SignalDirection[]).map((dir) => (
                  <label
                    key={dir}
                    className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 dark:border-slate-700 dark:text-slate-300"
                  >
                    <input
                      type="checkbox"
                      checked={directionSet.has(dir)}
                      onChange={(e) =>
                        setDirectionSet((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(dir);
                          else next.delete(dir);
                          return next;
                        })
                      }
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    {dir === "bullish" ? "Alcista" : "Bajista"}
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="mt-8 flex items-center justify-end border-t border-slate-200 pt-5 dark:border-slate-800">
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSubmit || submitting}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Rocket className="h-4 w-4" />
            )}
            Iniciar backtest
          </button>
        </div>
      </div>
    </main>
  );
}
