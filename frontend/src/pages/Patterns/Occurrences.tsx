import { useCallback, useEffect, useMemo, useState } from "react";

import { ExternalLink, Filter, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { OccurrenceTable } from "../../components/Patterns/OccurrenceTable";
import { PatternBreakdown } from "../../components/Patterns/PatternBreakdown";
import {
  getOccurrences,
  getOccurrencesSummary,
  getPatternCatalog,
} from "../../services/patternsApi";
import type { OccurrenceListFilters } from "../../services/patternsApi";
import type { OccurrenceSummary, PatternDefinition, PatternOccurrence } from "../../types/patterns";

/** Tope del backend en `GET /occurrences`. */
const PAGE_SIZE = 50;

/**
 * Timeframes seleccionables, lista fija igual que en `PatternList`.
 *
 * La alternativa era deducirlos de `summary.by_timeframe`, que es lo que la API
 * devuelve, pero eso convierte el filtro en una trampa: el desplegable solo
 * ofrece los timeframes que el resto de filtros ya dejaron pasar, así que al
 * filtrar por un símbolo sin ocurrencias en `1h` la opción desaparece y el
 * usuario que quería `1h` se queda sin forma de recuperarlo. Con la lista fija
 * siempre se puede elegir cualquier valor y ver un resultado honesto: cero
 * detecciones.
 */
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];

type Direction = "all" | "bullish" | "bearish";

/** Resumen vacío para no pintar `NaN` antes de que llegue la primera respuesta. */
const EMPTY_SUMMARY: OccurrenceSummary = {
  total: 0,
  distinct_patterns: 0,
  distinct_symbols: 0,
  first_occurrence: null,
  last_occurrence: null,
  bullish: 0,
  bearish: 0,
  by_pattern: [],
  by_symbol: [],
  by_timeframe: [],
};

export default function Occurrences() {
  const navigate = useNavigate();

  const [catalog, setCatalog] = useState<PatternDefinition[]>([]);
  const [summary, setSummary] = useState<OccurrenceSummary>(EMPTY_SUMMARY);
  const [rows, setRows] = useState<PatternOccurrence[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [pattern, setPattern] = useState("");
  const [direction, setDirection] = useState<Direction>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  useEffect(() => {
    void getPatternCatalog()
      .then(setCatalog)
      .catch(() => setCatalog([]));
  }, []);

  /**
   * La dirección no es un parámetro del backend: `GET /occurrences` no la
   * filtra. Se traduce a la lista de códigos con esa dirección según el
   * catálogo, que es la fuente autoritativa, en vez de adivinar por sufijo del
   * nombre: `RSI_EXIT_OVERSOLD` es `bullish` pese a su nombre, y un filtro por
   * sufijo lo clasificaría al revés.
   */
  const codesByDirection = useMemo(() => {
    const bullish = catalog.filter((d) => d.direction === "bullish").map((d) => d.code);
    const bearish = catalog.filter((d) => d.direction === "bearish").map((d) => d.code);
    return { bullish, bearish };
  }, [catalog]);

  /**
   * Filtros que van a la query. Se calculan aquí y no en el `useEffect` para
   * que la tabla y las tarjetas del resumen siempre se pidan con exactamente
   * los mismos criterios: si divergieran, el desglose hablaría de un conjunto y
   * la tabla de otro.
   */
  const filters = useMemo<OccurrenceListFilters>(() => {
    const byDirection =
      direction === "bullish"
        ? codesByDirection.bullish
        : direction === "bearish"
          ? codesByDirection.bearish
          : [];
    // Patrón y dirección se combinan: si se piden los dos, gana la intersección.
    // Sin intersección no habría forma de pedir "este patrón y además alcista".
    const selected =
      pattern && byDirection.length > 0
        ? [pattern].filter((code) => byDirection.includes(code))
        : pattern
          ? [pattern]
          : byDirection.length > 0
            ? byDirection
            : undefined;

    return {
      symbol: symbol || undefined,
      timeframe: timeframe || undefined,
      patterns: selected,
      date_from: from ? new Date(`${from}T00:00:00`).toISOString() : undefined,
      date_to: to ? new Date(`${to}T23:59:59.999`).toISOString() : undefined,
      page,
      page_size: PAGE_SIZE,
    };
  }, [symbol, timeframe, pattern, direction, codesByDirection, from, to, page]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Los dos van con los mismos filtros, salvo la paginación, que el
      // resumen no admite. La promesa se resuelve junta para no pintar un
      // resumen viejo junto a una tabla nueva.
      const [list, agg] = await Promise.all([
        getOccurrences(filters),
        getOccurrencesSummary(filters),
      ]);
      setRows(list.occurrences);
      setTotal(list.total);
      setSummary(agg);
      setError(null);
    } catch {
      setError("No se pudieron cargar las ocurrencias.");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void load();
  }, [load]);

  const resetFilters = () => {
    setSymbol("");
    setTimeframe("");
    setPattern("");
    setDirection("all");
    setFrom("");
    setTo("");
    setPage(1);
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const emptyDirection =
    direction !== "all" &&
    pattern &&
    codesByDirection[direction].length > 0 &&
    !codesByDirection[direction].includes(pattern);

  return (
    <main className="h-screen flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
            Ocurrencias de patrones
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Todas las detecciones de todos los escaneos
          </p>
        </div>

        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Símbolo
            </span>
            <input
              type="text"
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value);
                setPage(1);
              }}
              placeholder="BTCUSDT"
              className="w-32 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Timeframe
            </span>
            <select
              value={timeframe}
              onChange={(e) => {
                setTimeframe(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="">Todos</option>
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Patrón
            </span>
            <select
              value={pattern}
              onChange={(e) => {
                setPattern(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="">Todos</option>
              {catalog.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.short_label} ({d.code})
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Dirección
            </span>
            <select
              value={direction}
              onChange={(e) => {
                setDirection(e.target.value as Direction);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="all">Todas</option>
              <option value="bullish">Alcistas</option>
              <option value="bearish">Bajistas</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Desde
            </span>
            <input
              type="date"
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
              Hasta
            </span>
            <input
              type="date"
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </label>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refrescar
          </button>
          <button
            type="button"
            onClick={resetFilters}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <Filter className="h-4 w-4" />
            Limpiar
          </button>
        </div>

        {error && (
          <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            {error}
          </p>
        )}

        {emptyDirection && (
          <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
            {pattern} no es {direction === "bullish" ? "alcista" : "bajista"}. Quita el filtro de
            dirección o elige otro patrón.
          </p>
        )}

        <div className="mb-6">
          <PatternBreakdown summary={summary} />
        </div>

        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Detalle
            <span className="ml-2 text-sm font-normal text-slate-500 dark:text-slate-400">
              {total.toLocaleString("es-ES")}
            </span>
          </h2>
        </div>

        <OccurrenceTable
          occurrences={rows}
          onViewChart={() => undefined}
          onViewOccurrence={(occurrence) =>
            // El gráfico vive en el detalle de un escaneo, así que se salta al
            // job dueño de la detección y se pasa `?ts=`, que es lo que lee
            // `PatternChart` para centrar la vista.
            navigate(
              `/patterns/scans/${occurrence.scan_job_id}?ts=${encodeURIComponent(occurrence.timestamp)}`,
            )
          }
          emptyMessage="Sin ocurrencias para estos filtros."
        />

        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Página {page} de {pages}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={page >= pages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              Siguiente
            </button>
          </div>
        </div>

        <p className="mt-6 flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
          <ExternalLink className="h-3 w-3" />
          «Ver en gráfico» abre el escaneo que produjo la detección y centra el gráfico en esa vela.
        </p>
      </div>
    </main>
  );
}
