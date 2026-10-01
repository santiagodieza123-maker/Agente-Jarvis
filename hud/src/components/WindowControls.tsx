import { useState } from "react";

// Solo existen dentro de Tauri; en el navegador (desarrollo) no se renderizan.
export const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function win() {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow();
}

export function WindowControls() {
  const [through, setThrough] = useState(false);
  if (!inTauri()) return null;
  const toggleThrough = async () => {
    const next = !through;
    await (await win()).setIgnoreCursorEvents(next);
    setThrough(next);
  };
  return (
    <span className="winctl">
      <button onClick={async () => (await win()).minimize()} title="Minimizar" aria-label="Minimizar">–</button>
      <button className={through ? "on" : ""} onClick={toggleThrough} title="Click-through: el ratón atraviesa la ventana (se desactiva desde la barra de tareas)" aria-label="Click-through">◌</button>
      <button onClick={async () => (await win()).close()} title="Cerrar el HUD (el lanzador detiene al agente)" aria-label="Cerrar">✕</button>
    </span>
  );
}
