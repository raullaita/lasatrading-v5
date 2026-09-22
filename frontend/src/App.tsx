import {
  Activity,
  Bell,
  Database,
  LayoutDashboard,
  LineChart,
  Rocket,
  ScanSearch,
} from "lucide-react";
import { Link, NavLink, Route, Routes } from "react-router-dom";

const navItems = [
  { to: "/", label: "Inicio", icon: LayoutDashboard },
  { to: "/import", label: "Importación", icon: Database },
  { to: "/features", label: "Features", icon: LineChart },
  { to: "/patterns", label: "Patrones", icon: ScanSearch },
  { to: "/backtesting", label: "Backtesting", icon: Activity },
  { to: "/alerts", label: "Alertas", icon: Bell },
];

const modules = [
  { label: "Importación de Datos", icon: Database },
  { label: "Cálculo de Features", icon: LineChart },
  { label: "Detección de Patrones", icon: ScanSearch },
  { label: "Backtesting", icon: Activity },
  { label: "Alertas", icon: Bell },
  { label: "Ejecución", icon: Rocket },
];

function Sidebar() {
  return (
    <aside className="flex h-screen w-64 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white">
          <Rocket className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-900">LaSaTrading v5</p>
          <p className="text-xs text-slate-500">Plataforma de trading</p>
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
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-slate-200 px-6 py-4">
        <p className="text-xs text-slate-500">Entorno: desarrollo</p>
      </div>
    </aside>
  );
}

function Welcome() {
  return (
    <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-600 text-white">
          <Rocket className="h-8 w-8" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900">LaSaTrading v5</h1>
        <p className="mt-2 text-slate-600">
          El sistema se ha inicializado correctamente. Backend y frontend están operativos y
          listos para el desarrollo.
        </p>
        <div className="mt-6 flex items-center justify-center gap-2 rounded-xl bg-emerald-50 py-3 text-sm font-medium text-emerald-700">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-500" />
          Servicios activos
        </div>
        <div className="mt-8 grid grid-cols-2 gap-3 text-left sm:grid-cols-3">
          {modules.map(({ label, icon: Icon }) => (
            <div
              key={label}
              className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3"
            >
              <Icon className="h-4 w-4 shrink-0 text-indigo-600" />
              <span className="text-xs font-medium text-slate-700">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

function ModulePlaceholder({ module }: { module: string }) {
  return (
    <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">{module}</h1>
        <p className="mt-2 text-sm text-slate-600">
          Este módulo se implementará en futuras tareas del proyecto.
        </p>
      </div>
    </main>
  );
}

export default function App() {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />
      <Routes>
        <Route path="/" element={<Welcome />} />
        <Route path="/import" element={<ModulePlaceholder module="Importación de Datos" />} />
        <Route path="/features" element={<ModulePlaceholder module="Cálculo de Features" />} />
        <Route path="/patterns" element={<ModulePlaceholder module="Detección de Patrones" />} />
        <Route path="/backtesting" element={<ModulePlaceholder module="Backtesting" />} />
        <Route path="/alerts" element={<ModulePlaceholder module="Alertas" />} />
        <Route
          path="*"
          element={
            <main className="flex h-screen flex-1 items-center justify-center bg-slate-50 p-8">
              <div className="text-center">
                <p className="text-lg font-semibold text-slate-900">404</p>
                <Link to="/" className="mt-2 inline-block text-sm text-indigo-600 hover:underline">
                  Volver al inicio
                </Link>
              </div>
            </main>
          }
        />
      </Routes>
    </div>
  );
}