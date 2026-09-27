import { useEffect, useMemo, useState } from "react";

import { Search } from "lucide-react";

import type { BinanceSymbol } from "../../../types/dataImport";

export interface SymbolSelectorProps {
  available: BinanceSymbol[];
  selected: string[];
  onToggle: (symbol: string) => void;
}

function matches(symbol: string, query: string): boolean {
  return symbol.toLowerCase().includes(query.toLowerCase());
}

export function SymbolSelector({ available, selected, onToggle }: SymbolSelectorProps) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const filtered = useMemo(
    () =>
      available
        .filter((s) => s.status === "TRADING" && matches(s.symbol, debounced))
        .sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [available, debounced],
  );

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar símbolo (BTCUSDT)…"
          className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-indigo-900"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {selected.map((sym) => (
          <button
            key={sym}
            type="button"
            onClick={() => onToggle(sym)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            {sym}
            <span className="text-indigo-200">×</span>
          </button>
        ))}
      </div>
      <div className="max-h-56 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-800">
        {filtered.length === 0 && (
          <p className="px-4 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
            Sin resultados{debounced ? ` para "${debounced}"` : ""}.
          </p>
        )}
        {filtered.slice(0, 80).map((s) => (
          <button
            key={s.symbol}
            type="button"
            onClick={() => onToggle(s.symbol)}
            className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm transition-colors ${
              selected.includes(s.symbol)
                ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"
                : "text-slate-700 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            <span>
              <span className="font-medium">{s.base_asset}</span>
              <span className="text-slate-400 dark:text-slate-500"> / {s.quote_asset}</span>
            </span>
            <span className="text-xs text-slate-400 dark:text-slate-500">{s.symbol}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
