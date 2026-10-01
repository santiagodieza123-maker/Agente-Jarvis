import { useEffect, useState } from "react";

// Solo existen dentro de Tauri; en el navegador (desarrollo) no se renderizan.
export const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function win() {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow();
}
async function setClickThrough(enabled: boolean) {
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("set_click_through", { enabled });
}

/** `needsInput`: hay una aprobación pendiente; el click-through se desactiva solo para que se pueda pulsar Permitir/Denegar. */
export function WindowControls({ needsInput }: { needsInput: boolean }) {
  const [through, setThrough] = useState(false);
  useEffect(() => {
    if (!inTauri()) return;
    let off: (() => void) | undefined, dead = false;
    import("@tauri-apps/api/event").then(({ listen }) =>
      listen<boolean>("click-through", (e) => setThrough(e.payload)).then((u) => { if (dead) u(); else off = u; }));
    return () => { dead = true; off?.(); };
  }, []);
  useEffect(() => { if (needsInput && through) void setClickThrough(false); }, [needsInput, through]);
  if (!inTauri()) return null;
  return (
    <span className="winctl">
      <button onClick={async () => (await win()).minimize()} title="Minimizar" aria-label="Minimizar">–</button>
      <button className={through ? "on" : ""} onClick={() => setClickThrough(!through)} aria-label="Click-through"
              title="Click-through: el ratón atraviesa la ventana. Ctrl+Shift+F9 lo activa y desactiva aunque no puedas hacer clic; se desactiva solo cuando hay una aprobación pendiente">◌</button>
      <button onClick={async () => (await win()).close()} title="Cerrar el HUD (el lanzador detiene al agente)" aria-label="Cerrar">✕</button>
    </span>
  );
}
