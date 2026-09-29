import {
  Activity,
  Bell,
  Database,
  LayoutDashboard,
  LineChart,
  Loader2,
  Moon,
  Rocket,
  ScanSearch,
  Sun,
  TableProperties,
  TrendingUp,
} from "lucide-react";
import { lazy, Suspense } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";

import { useTheme } from "./theme/theme";
import FeatureDetail from "./pages/Features/FeatureDetail";
import FeatureList from "./pages/Features/FeatureList";
import NewFeatureJob from "./pages/Features/NewFeatureJob";
import ImportDetail from "./pages/DataImport/ImportDetail";
import ImportList from "./pages/DataImport/ImportList";
import NewImport from "./pages/DataImport/NewImport";
import DataExplorer from "./pages/DataExplorer/DataExplorer";
import DataExplorerChart from "./pages/DataExplorer/DataExplorerChart";

// Las cuatro páginas de patrones van en carga diferida. Suman unos 67 kB y
// ninguna hace falta en el primer render: quien entra por el panel de Welcome
// no las va a mirar nunca, y quien viene de "Nuevo escaneo" carga una sola.
// Con esto el chunk inicial se queda por debajo del umbral de 500 kB que avisa
// Vite.
const PatternList = lazy(() => import("./pages/Patterns/PatternList"));
const NewPatternScan = lazy(() => import("./pages/Patterns/NewPatternScan"));
const Occurrences = lazy(() => import("./pages/Patterns/Occurrences"));
const ScanDetail = lazy(() => import("./pages/Patterns/ScanDetail"));
// Backtesting: mismas razones que patrones, con el detalle como la hoja pesada.
const BacktestList = lazy(() => import("./pages/Backtesting/BacktestList"));
const NewBacktest = lazy(() => import("./pages/Backtesting/NewBacktest"));
const BacktestDetail = lazy(() => import("./pages/Backtesting/BacktestDetail"));
const Alerts = lazy(() => import("./pages/Alerts/Alerts"));
const NewAlertRule = lazy(() => import("./pages/Alerts/NewAlertRule"));
const WalkForwardList = lazy(() => import("./pages/WalkForward/WalkForwardList"));
const NewWalkForward = lazy(() => import("./pages/WalkForward/NewWalkForward"));
const WalkForwardDetail = lazy(() => import("./pages/WalkForward/WalkForwardDetail"));

/**
 * Placeholder de carga de las rutas diferidas.
 *
 * Se ve un instante en cada salto dentro del módulo, así que muestra un
 * indicador y no un blanco: un salto a `/patterns/occurrences` baja la tabla
 * entera y el cambio de estado se percibe.
 */
function RouteFallback() {
  return (
    <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 dark:bg-slate-950">
      <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
        Cargando…
      </div>
    </main>
  );
}

const navItems = [
  { to: "/", label: "Inicio", icon: LayoutDashboard },
  { to: "/import", label: "Importación", icon: Database },
  { to: "/data", label: "Datos", icon: TableProperties },
  { to: "/data-explorer", label: "Explorador de Gráficos", icon: LineChart },
  { to: "/features", label: "Indicadores", icon: LineChart },
  { to: "/patterns", label: "Patrones", icon: ScanSearch },
  { to: "/backtesting", label: "Backtesting", icon: Activity },
  { to: "/walk-forward", label: "Walk-forward", icon: TrendingUp },
  { to: "/alerts", label: "Alertas", icon: Bell },
];

const modules = [
  { label: "Importación de Datos", icon: Database },
  { label: "Cálculo de Features", icon: LineChart },
  { label: "Detección de Patrones", icon: ScanSearch },
  { label: "Backtesting", icon: Activity },
  { label: "Walk-forward", icon: TrendingUp },
  { label: "Alertas", icon: Bell },
  { label: "Ejecución", icon: Rocket },
];

function Sidebar() {
  const { theme, toggle } = useTheme();

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-5 dark:border-slate-800">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white">
          <Rocket className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">LaSaTrading v5</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Plataforma de trading</p>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              }`
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-slate-200 px-4 py-4 dark:border-slate-800">
        <button
          type="button"
          onClick={toggle}
          className="flex w-full items-center justify-between rounded-lg px-2 py-2 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          title={theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
        >
          <span>Modo {theme === "dark" ? "oscuro" : "claro"}</span>
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <p className="mt-2 px-2 text-xs text-slate-500 dark:text-slate-400">Entorno: desarrollo</p>
      </div>
    </aside>
  );
}

function Welcome() {
  return (
    <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-600 text-white">
          <Rocket className="h-8 w-8" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">LaSaTrading v5</h1>
        <p className="mt-2 text-slate-600 dark:text-slate-300">
          El sistema se ha inicializado correctamente. Backend y frontend están operativos y listos
          para el desarrollo.
        </p>
        <div className="mt-6 flex items-center justify-center gap-2 rounded-xl bg-emerald-50 py-3 text-sm font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-500" />
          Servicios activos
        </div>
        <div className="mt-8 grid grid-cols-2 gap-3 text-left sm:grid-cols-3">
          {modules.map(({ label, icon: Icon }) => (
            <div
              key={label}
              className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800"
            >
              <Icon className="h-4 w-4 shrink-0 text-indigo-600" />
              <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                {label}
              </span>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

export default function App() {
  return (
    <div className="flex min-h-screen bg-slate-50 dark:bg-slate-950">
      <Sidebar />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Welcome />} />
          <Route path="/import" element={<ImportList />} />
          <Route path="/import/new" element={<NewImport />} />
          <Route path="/import/:jobId" element={<ImportDetail />} />
          <Route path="/data" element={<DataExplorer />} />
          <Route path="/data-explorer" element={<DataExplorerChart />} />
          <Route path="/features" element={<FeatureList />} />
          <Route path="/features/new" element={<NewFeatureJob />} />
          <Route path="/features/:jobId" element={<FeatureDetail />} />
          {/*
          Rutas de patrones. El orden importa: `/patterns/new` y
          `/patterns/occurrences` son literales y tienen que declararse ANTES que
          `/patterns/scans/:jobId`. React Router 6 puntua por segmentos, así que
          un literal siempre gana a un parámetro y el orden no rompería nada...
          pero dejarlos en ese orden hace evidente que es deliberado, y si
          mañana alguien mete `/patterns/:algo` el conflicto se ve de inmediato.
        */}
          <Route path="/patterns" element={<PatternList />} />
          <Route path="/patterns/new" element={<NewPatternScan />} />
          <Route path="/patterns/occurrences" element={<Occurrences />} />
          <Route path="/patterns/scans/:jobId" element={<ScanDetail />} />
          {/*
          Rutas de backtesting. `new` es literal y va ANTES que `runs/:runId`:
          el mismo criterio de orden que /patterns, para que un futuro
          `/backtesting/:algo` colisione a la vista.
        */}
          <Route path="/backtesting" element={<BacktestList />} />
          <Route path="/backtesting/new" element={<NewBacktest />} />
          <Route path="/backtesting/runs/:runId" element={<BacktestDetail />} />
          <Route path="/walk-forward" element={<WalkForwardList />} />
          <Route path="/walk-forward/new" element={<NewWalkForward />} />
          <Route path="/walk-forward/runs/:runId" element={<WalkForwardDetail />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/alerts/new" element={<NewAlertRule />} />
          <Route
            path="*"
            element={
              <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8 dark:bg-slate-950">
                <div className="text-center">
                  <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">404</p>
                  <Link
                    to="/"
                    className="mt-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400"
                  >
                    Volver al inicio
                  </Link>
                </div>
              </main>
            }
          />
        </Routes>
      </Suspense>
    </div>
  );
}
