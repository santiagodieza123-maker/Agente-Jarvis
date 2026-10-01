import { useEffect, useState } from "react";
import { Approvals } from "./components/Approvals";
import { AuditPanel } from "./components/AuditPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { Console } from "./components/Console";
import { ExtensionsPanel } from "./components/ExtensionsPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { Orb } from "./components/Orb";
import { PermissionsPanel } from "./components/PermissionsPanel";
import { Timeline } from "./components/Timeline";
import { WindowControls } from "./components/WindowControls";
import { ACCENT_COLOR } from "./config";
import { useJarvis } from "./useJarvis";

type Tab = "consola" | "memoria" | "permisos" | "auditoría" | "mcp" | "config";
const TABS: Tab[] = ["consola", "memoria", "permisos", "auditoría", "mcp", "config"];

export default function App() {
  const { state, send, submitTask, dispatch } = useJarvis();
  const [tab, setTab] = useState<Tab>("consola");

  const accent = state.config?.values.accent;
  useEffect(() => { document.documentElement.style.setProperty("--c", ACCENT_COLOR[accent ?? "cian"] ?? ACCENT_COLOR.cian); }, [accent]);

  useEffect(() => {   // los avisos se descartan solos
    if (!state.notice) return;
    const id = state.notice.id, t = window.setTimeout(() => dispatch({ kind: "clear_notice", id }), 6000);
    return () => window.clearTimeout(t);
  }, [state.notice, dispatch]);

  return (
    <main className={`hud ${state.agent}`}>
      <header data-tauri-drag-region>
        <span data-tauri-drag-region>J.A.R.V.I.S.</span>
        <span className="status" data-tauri-drag-region>{state.conn === "open" || state.agent === "killed" ? state.agent.toUpperCase() : state.conn.toUpperCase()}</span>
        <button className="panic" onClick={() => send({ type: "panic" })} title="Detiene al agente y a sus procesos hijos">PÁNICO</button>
        <WindowControls />
      </header>
      <div className="orb"><Orb state={state.agent} /></div>
      <div className="tabs">
        <nav role="tablist">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>
          ))}
        </nav>
        {state.notice && <div className={`notice ${state.notice.level}`} role="status" data-testid="notice">{state.notice.text}</div>}
        {tab === "consola" && <Console chat={state.chat} disabled={state.conn !== "open"} onSubmit={submitTask} />}
        {tab === "memoria" && <MemoryPanel memory={state.memory} send={send} />}
        {tab === "permisos" && <PermissionsPanel perms={state.permissions} send={send} />}
        {tab === "mcp" && <ExtensionsPanel ext={state.extensions} send={send} />}
        {tab === "config" && <ConfigPanel config={state.config} send={send} />}
        {tab === "auditoría" && <AuditPanel audit={state.audit} verified={state.auditVerified} send={send} />}
      </div>
      <Timeline items={state.timeline} />
      <Approvals items={state.approvals} onDecide={(a, granted) => send({ type: "approval", id: a.id, granted })} />
    </main>
  );
}
