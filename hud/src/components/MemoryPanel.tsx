import { useState } from "react";
import type { HudMessage, MemorySnapshot } from "../events";

const when = (ts: number) => new Date(ts * 1000).toLocaleString();

export function MemoryPanel({ memory, send }: { memory: MemorySnapshot | null; send: (m: HudMessage) => void }) {
  const [kind, setKind] = useState("preferencia");
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null);
  if (!memory) return <section className="panel"><h2>MEMORIA</h2><p className="empty">Cargando…</p></section>;
  const full = memory.notes.length >= memory.limits.notes;

  return (
    <section className="panel mem" data-testid="memory-panel">
      <h2>MEMORIA <span className="count">{memory.notes.length}/{memory.limits.notes}</span></h2>
      <p className="hint">Notas que Jarvis recibe como contexto en cada tarea. Solo tú puedes crearlas o cambiarlas.</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (t) { send({ type: "memory.add", kind, content: t }); setText(""); } }}>
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Tipo de nota">
          {memory.kinds.map((k) => <option key={k}>{k}</option>)}
        </select>
        <input value={text} maxLength={memory.limits.content} onChange={(e) => setText(e.target.value)}
               placeholder={full ? "límite de notas alcanzado" : "Nueva nota…"} disabled={full} aria-label="Contenido de la nota" />
        <button disabled={full || !text.trim()}>Añadir</button>
      </form>
      <ul className="notes">
        {memory.notes.map((n) => (
          <li key={n.id} data-testid="note">
            <span className="tag">{n.kind}</span>
            {editing?.id === n.id ? (
              <form className="row grow" onSubmit={(e) => { e.preventDefault(); const t = editing.text.trim(); if (t) send({ type: "memory.update", id: n.id, content: t }); setEditing(null); }}>
                <input autoFocus value={editing.text} maxLength={memory.limits.content} onChange={(e) => setEditing({ id: n.id, text: e.target.value })} />
                <button>Guardar</button><button type="button" onClick={() => setEditing(null)}>Cancelar</button>
              </form>
            ) : (
              <>
                <span className="grow">{n.content}</span>
                <button onClick={() => setEditing({ id: n.id, text: n.content })}>Editar</button>
                <button className="deny" onClick={() => send({ type: "memory.delete", id: n.id })} aria-label={`Borrar nota ${n.id}`}>Borrar</button>
              </>
            )}
          </li>
        ))}
        {!memory.notes.length && <li className="empty">Sin notas</li>}
      </ul>
      <h2 className="sub">HISTORIAL DE TAREAS
        {memory.episodes.length > 0 && <button className="deny small" onClick={() => send({ type: "memory.clear_episodes" })}>Limpiar</button>}
      </h2>
      <ul className="episodes">
        {memory.episodes.map((e) => (
          <li key={e.id} data-testid="episode" title={e.answer}>
            <span className={`dot ${e.status === "done" ? "ok" : "failed"}`} />
            <span className="grow">{e.goal}</span><em>{e.steps} pasos · {when(e.ts)}</em>
          </li>
        ))}
        {!memory.episodes.length && <li className="empty">Sin tareas todavía</li>}
      </ul>
    </section>
  );
}
