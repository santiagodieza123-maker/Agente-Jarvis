import { useState } from "react";
import { parsePre, preToText, recipeParams, successRate } from "../recipes";
import type { HudMessage, MemorySnapshot, Recipe } from "../events";

const when = (ts: number) => new Date(ts * 1000).toLocaleString();

function RecipeCard({ r, send }: { r: Recipe; send: (m: HudMessage) => void }) {
  const names = recipeParams(r);
  const [vals, setVals] = useState<Record<string, string>>({});                       // lo que el usuario ha editado
  const valueOf = (n: string) => vals[n] ?? r.params[n] ?? "";                       // si no, el valor por defecto de la receta
  const [pre, setPre] = useState(preToText(r.pre));
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const savePre = () => { const p = parsePre(pre); if (!p.ok) { setErr(p.error); return; } setErr(""); send({ type: "recipes.set_preconditions", id: r.id, items: p.items }); };
  return (
    <li className="recipe" data-testid={`recipe-${r.name}`}>
      <div className="row">
        <strong className="grow">{r.name}</strong>
        <em title="Ejecuciones correctas / totales">{successRate(r)}</em>
        <button onClick={() => send({ type: "recipes.run", id: r.id, params: Object.fromEntries(names.map((n) => [n, valueOf(n)])) })} data-testid={`run-${r.name}`} title="Se repite sin llamar al modelo; cada paso pasa por la política y las confirmaciones">▶ Ejecutar</button>
        <button className="deny small" onClick={() => { if (window.confirm(`¿Borrar la receta «${r.name}»?`)) send({ type: "recipes.delete", id: r.id }); }}>Borrar</button>
      </div>
      <p className="hint">Objetivo original: {r.goal}</p>
      {r.tainted && <p className="danger">⚠ La tarea original leyó contenido no confiable: revisa los pasos antes de ejecutarla.</p>}
      {r.last_error && <p className="warn" role="alert">Último fallo: {r.last_error}</p>}
      {names.length > 0 && (
        <div className="params">{names.map((n) => (
          <label key={n}><span>{n}</span><input value={valueOf(n)} onChange={(e) => setVals({ ...vals, [n]: e.target.value })} data-testid={`param-${n}`} /></label>
        ))}</div>
      )}
      <button className="small" onClick={() => setOpen(!open)}>{open ? "Ocultar pasos" : `Ver ${r.steps.length} pasos`}</button>
      {open && (
        <>
          <ol className="steps">
            {r.steps.map((st, i) => (
              <li key={i}><code>{st.tool}</code>{" "}
                {Object.entries(st.args).map(([k, v]) => (
                  <span key={k} className="arg">{k}=<q>{typeof v === "string" ? v : JSON.stringify(v)}</q>
                    {typeof v === "string" && !/^\{\{.*\}\}$/.test(v) && (
                      <button className="small" title="Convertir este valor en un parámetro" onClick={() => { const n = window.prompt("Nombre del parámetro (a-z, 0-9, _):", k); if (n) send({ type: "recipes.param", id: r.id, step: i, arg: k, name: n.trim() }); }}>{"{}"}</button>
                    )}
                  </span>
                ))}
              </li>
            ))}
          </ol>
          <label className="prebox"><span>Precondiciones (una por línea: «ruta: …» o «ventana: …»)</span>
            <textarea rows={2} value={pre} onChange={(e) => setPre(e.target.value)} spellCheck={false} data-testid={`pre-${r.name}`} /></label>
          {err && <p className="warn" role="alert">{err}</p>}
          <button className="small" onClick={savePre}>Guardar precondiciones</button>
        </>
      )}
    </li>
  );
}

export function MemoryPanel({ memory, send }: { memory: MemorySnapshot | null; send: (m: HudMessage) => void }) {
  const [kind, setKind] = useState("preferencia");
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null);
  if (!memory) return <section className="panel"><h2>RECUERDOS</h2><p className="empty">Despertando…</p></section>;
  const full = memory.notes.length >= memory.limits.notes;

  return (
    <section className="panel mem" data-testid="memory-panel">
      <h2>RECUERDOS <span className="count">{memory.notes.length}/{memory.limits.notes}</span></h2>
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
      <h2 className="sub">RECETAS <span className="count">{(memory.recipes ?? []).length}</span></h2>
      <p className="hint">Tareas que funcionaron, guardadas desde el historial. Se repiten sin llamar al modelo y no concede permisos: cada paso vuelve a pedir lo que pediría normalmente.</p>
      <ul className="recipes">
        {(memory.recipes ?? []).map((r) => <RecipeCard key={r.id} r={r} send={send} />)}
        {!(memory.recipes ?? []).length && <li className="empty">Sin recetas: guarda una desde una tarea completada del historial</li>}
      </ul>
      <h2 className="sub">HISTORIAL DE TAREAS
        {memory.episodes.length > 0 && <button className="deny small" onClick={() => send({ type: "memory.clear_episodes" })}>Limpiar</button>}
      </h2>
      <ul className="episodes">
        {memory.episodes.map((e) => (
          <li key={e.id} data-testid="episode" title={e.answer}>
            <span className={`dot ${e.status === "done" ? "ok" : "failed"}`} />
            <span className="grow">{e.goal}</span><em>{e.steps} pasos · {when(e.ts)}</em>
            {e.saveable && <button className="small" data-testid={`save-recipe-${e.id}`} title="Guardar las acciones de esta tarea para repetirla sin el modelo"
              onClick={() => { const n = window.prompt("Nombre de la receta:", e.goal.slice(0, 40)); if (n) send({ type: "recipes.save", episode_id: e.id, name: n.trim() }); }}>Guardar receta</button>}
          </li>
        ))}
        {!memory.episodes.length && <li className="empty">Sin tareas todavía</li>}
      </ul>
    </section>
  );
}
