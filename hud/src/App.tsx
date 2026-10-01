import { useEffect, useState } from "react";
import { Approvals } from "./components/Approvals";
import { AuditPanel } from "./components/AuditPanel";
import { Console } from "./components/Console";
import { MemoryPanel } from "./components/MemoryPanel";
import { Orb } from "./components/Orb";
import { PermissionsPanel } from "./components/PermissionsPanel";
import { Timeline } from "./components/Timeline";
import { useJarvis } from "./useJarvis";

type Tab = "consola" | "memoria" | "permisos" | "auditoría";

export default function App() {
  const { state, send, submitTask, dispatch } = useJarvis();
  const [tab, setTab] = useState<Tab>("consola");

  useEffect(() => {   // los avisos se descartan solos
    if (!state.notice) return;
    const id = state.notice.id, t = window.setTimeout(() => dispatch({ kind: "clear_notice", id }), 6000);
    return () => window.clearTimeout(t);
  }, [state.notice, dispatch]);

  return (
    <main className={`hud ${state.agent}`}>
      <header>
        <span>J.A.R.V.I.S.</span>
        <span className="status">{state.conn === "open" || state.agent === "killed" ? state.agent.toUpperCase() : state.conn.toUpperCase()}</span>
        <button className="panic" onClick={() => send({ type: "panic" })} title="Detiene al agente y a sus procesos hijos">PÁNICO</button>
      </header>
      <div className="orb"><Orb state={state.agent} /></div>
      <div className="tabs">
        <nav role="tablist">
          {(["consola", "memoria", "permisos", "auditoría"] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>
          ))}
        </nav>
        {state.notice && <div className={`notice ${state.notice.level}`} role="status" data-testid="notice">{state.notice.text}</div>}
        {tab === "consola" && <Console chat={state.chat} disabled={state.conn !== "open"} onSubmit={submitTask} />}
        {tab === "memoria" && <MemoryPanel memory={state.memory} send={send} />}
        {tab === "permisos" && <PermissionsPanel perms={state.permissions} send={send} />}
        {tab === "auditoría" && <AuditPanel audit={state.audit} verified={state.auditVerified} send={send} />}
      </div>
      <Timeline items={state.timeline} />
      <Approvals items={state.approvals} onDecide={(a, granted) => send({ type: "approval", id: a.id, granted })} />
    </main>
  );
}
