import { useState } from "react";
import { X } from "lucide-react";

/**
 * Confirmación de borrado de uno o varios jobs.
 *
 * Vive en `ui/` porque los tres módulos que borran trabajos necesitan el mismo
 * diálogo, pero no pueden compartir el texto: lo que arrastra el borrado es
 * distinto en cada uno. El de DataImport se lleva sus combinaciones, el de
 * Features sus features calculadas, el de Patterns las ocurrencias y los logs.
 * Un texto único "para todos" acabaría mintiendo en dos de los tres, así que el
 * dominio declara qué se borra y el componente solo lo compone.
 *
 * Pide escribir BORRAR porque desde las listas el borrado se dispara con las
 * casillas marcadas y un clic de más se lleva semanas de trabajo.
 */
export function DeleteJobModal({
  open,
  jobIds,
  /** Cómo llama el módulo a un trabajo: «escaneo» en patrones, «job» elsewhere. */
  itemNoun,
  /** Lo que arrastra el borrado, sin punto final. */
  consequence,
  onClose,
  onConfirm,
  busy,
}: {
  open: boolean;
  jobIds: string[];
  itemNoun: string;
  consequence: string;
  onClose: () => void;
  onConfirm: () => void;
  busy: boolean;
}) {
  const [confirmText, setConfirmText] = useState("");

  if (!open) return null;

  const confirmed = confirmText === "BORRAR";
  const count = jobIds.length;

  const close = () => {
    setConfirmText("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-xl border border-rose-200 bg-white p-6 shadow-xl dark:border-rose-900 dark:bg-slate-900">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-rose-700 dark:text-rose-400">
            Borrar {count} {itemNoun}
            {count !== 1 ? "s" : ""}
          </h2>
          <button
            type="button"
            onClick={close}
            className="rounded-lg p-1 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5 text-slate-500 dark:text-slate-400" />
          </button>
        </div>

        <p className="mb-2 text-sm text-slate-700 dark:text-slate-300">
          ¿Estás seguro? Se borrará{count === 1 ? " el" : "n los"} {itemNoun}
          {count === 1 ? "" : "s"} seleccionado{count === 1 ? "" : "s"}, {consequence}. Esta acción
          no se puede deshacer.
        </p>

        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400">
          Escribe <span className="font-bold text-rose-600 dark:text-rose-400">BORRAR</span> para
          confirmar:
        </label>
        <input
          type="text"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder="BORRAR"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-rose-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        />

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={close}
            disabled={busy}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!confirmed || busy}
            className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {busy ? "Borrando…" : "Borrar"}
          </button>
        </div>
      </div>
    </div>
  );
}
