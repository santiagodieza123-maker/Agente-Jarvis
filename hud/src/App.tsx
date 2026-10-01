import { Approvals } from "./components/Approvals";
import { Console } from "./components/Console";
import { Orb } from "./components/Orb";
import { Timeline } from "./components/Timeline";
import { useJarvis } from "./useJarvis";

export default function App() {
  const { state, send, submitTask } = useJarvis();
  return (
    <main className={`hud ${state.agent}`}>
      <header>
        <span>J.A.R.V.I.S.</span>
        <span className="status">{state.conn === "open" || state.agent === "killed" ? state.agent.toUpperCase() : state.conn.toUpperCase()}</span>
        <button className="panic" onClick={() => send({ type: "panic" })} title="Detiene al agente y a sus procesos hijos">PÁNICO</button>
      </header>
      <div className="orb"><Orb state={state.agent} /></div>
      <Console chat={state.chat} disabled={state.conn !== "open"} onSubmit={submitTask} />
      <Timeline items={state.timeline} />
      <Approvals items={state.approvals} onDecide={(a, granted) => send({ type: "approval", id: a.id, granted })} />
    </main>
  );
}
