import { useEffect, useState } from "react";
import { Approvals } from "./components/Approvals";
import { AuditPanel } from "./components/AuditPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { Console } from "./components/Console";
import { ExtensionsPanel } from "./components/ExtensionsPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { Orb } from "./components/Orb";
import { PermissionsPanel } from "./components/PermissionsPanel";
import { VoiceBar } from "./components/VoiceBar";
import { useVoice } from "./voice/useVoice";
import { VisionPanel } from "./components/VisionPanel";
import { SystemPanel } from "./components/SystemPanel";
import { Timeline } from "./components/Timeline";
import { WindowControls, inTauri } from "./components/WindowControls";
import { SIZES, readCompact, saveCompact } from "./compact";
import { applyTheme } from "./themes";
import { useJarvis } from "./useJarvis";

type Tab = "consola" | "memoria" | "permisos" | "auditoría" | "mcp" | "visión" | "sistema" | "config";
const TABS: Tab[] = ["consola", "memoria", "permisos", "auditoría", "mcp", "visión", "sistema", "config"];

export default function App() {
  const { state, send, submitTask, dispatch } = useJarvis();
  const [tab, setTab] = useState<Tab>("consola");
  const [compact, setCompact] = useState(readCompact);
  const toggleCompact = async () => {
    const next = !compact;
    setCompact(next); saveCompact(next);
    if (inTauri()) {                                               // la ventana de Tauri cambia de tamaño con el modo
      try {
        const [{ getCurrentWindow }, { LogicalSize }] = await Promise.all([import("@tauri-apps/api/window"), import("@tauri-apps/api/dpi")]);
        const [w, h] = next ? SIZES.compact : SIZES.full;
        await getCurrentWindow().setSize(new LogicalSize(w, h));
      } catch { /* sin permiso o sin ventana: solo cambia el diseño */ }
    }
  };

  // Solo se habla la respuesta final (cuando el agente vuelve a reposo), no los avisos intermedios («paso 2/5», «esperando cuota»…)
  const lastMsg = state.chat[state.chat.length - 1];
  const lastAnswer = state.agent === "idle" && lastMsg?.who === "jarvis" ? { text: lastMsg.text, key: state.chat.length } : null;
  const voice = useVoice({ send, onText: submitTask, transcript: state.transcript, lastAnswer });
  useEffect(() => {                                              // Ctrl+Espacio: hablar / enviar, sin tocar el ratón
    const h = (e: KeyboardEvent) => { if (e.ctrlKey && e.code === "Space" && !e.repeat) { e.preventDefault(); voice.togglePtt(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [voice.togglePtt]);                                         // eslint-disable-line react-hooks/exhaustive-deps
  const accent = state.config?.values.accent;
  useEffect(() => { applyTheme(accent); }, [accent]);

  useEffect(() => {   // los avisos se descartan solos
    if (!state.notice) return;
    const id = state.notice.id, t = window.setTimeout(() => dispatch({ kind: "clear_notice", id }), 6000);
    return () => window.clearTimeout(t);
  }, [state.notice, dispatch]);

  return (
    <main className={`hud ${state.agent}${compact ? " compact" : ""}`}>
      <header data-tauri-drag-region>
        <span data-tauri-drag-region>J.A.R.V.I.S.</span>
        <span className="status" data-tauri-drag-region>{state.conn === "open" || state.agent === "killed" ? state.agent.toUpperCase() : state.conn.toUpperCase()}</span>
        {voice.supported && <button className={`micbtn${voice.ptt || voice.wake ? " rec" : ""}`} onClick={voice.togglePtt} title="Hablar (Ctrl+Espacio)" aria-label="Hablar" data-testid="mic-header">🎙</button>}
        <button className="compactbtn" onClick={toggleCompact} title={compact ? "Expandir el HUD" : "Modo compacto: solo el reactor"} aria-label="Modo compacto" data-testid="compact-toggle">{compact ? "⤢" : "⤡"}</button>
        <button className="panic" onClick={() => send({ type: "panic" })} title="Detiene al agente y a sus procesos hijos">PÁNICO</button>
        <WindowControls needsInput={state.approvals.length > 0} />
      </header>
      <div className="orb"><Orb state={state.agent} theme={accent} compact={compact} level={voice.level} /></div>
      {compact && <p className="compact-status" data-testid="compact-status">{state.plan || (state.conn === "open" ? "Listo" : "Sin conexión")}</p>}
      <div className="tabs">
        <nav role="tablist">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>
          ))}
        </nav>
        {state.notice && <div className={`notice ${state.notice.level}`} role="status" data-testid="notice">{state.notice.text}</div>}
        {tab === "consola" && <VoiceBar voice={voice} />}
        {tab === "consola" && <Console chat={state.chat} disabled={state.conn !== "open"} onSubmit={submitTask} />}
        {tab === "memoria" && <MemoryPanel memory={state.memory} send={send} />}
        {tab === "permisos" && <PermissionsPanel perms={state.permissions} send={send} />}
        {tab === "mcp" && <ExtensionsPanel ext={state.extensions} send={send} />}
        {tab === "visión" && <VisionPanel frame={state.frame} />}
        {tab === "sistema" && <SystemPanel stats={state.stats} />}
        {tab === "config" && <ConfigPanel config={state.config} send={send} />}
        {tab === "auditoría" && <AuditPanel audit={state.audit} verified={state.auditVerified} send={send} />}
      </div>
      <Timeline items={state.timeline} />
      <Approvals items={state.approvals} onDecide={(a, granted) => send({ type: "approval", id: a.id, granted })} />
    </main>
  );
}
