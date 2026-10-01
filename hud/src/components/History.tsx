import { useMemo, useState } from "react";
import type { HudState } from "../store";
import { EMPTY_TRAIL } from "../copy";

interface Entry { ask: string; answer?: string }

/** Agrupa el chat en tareas: lo que pediste y lo que respondió Jarvis (los avisos intermedios se descartan). */
export function entriesOf(chat: HudState["chat"]): Entry[] {
  const out: Entry[] = [];
  for (const m of chat) {
    if (m.who === "user") out.push({ ask: m.text });
    else if (out.length) out[out.length - 1].answer = m.text;
  }
  return out;
}

/** «Estela»: capa sobre la esfera con las tareas pasadas; se pueden filtrar, repetir o copiar. */
export function History({ chat, timeline, disabled, onRepeat, onClose }: {
  chat: HudState["chat"]; timeline: HudState["timeline"]; disabled: boolean; onRepeat: (t: string) => void; onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  const all = useMemo(() => entriesOf(chat), [chat]);
  const list = all.map((e, i) => ({ ...e, i })).filter((e) => !q || (e.ask + " " + (e.answer ?? "")).toLowerCase().includes(q.toLowerCase())).reverse();
  const copy = async (i: number, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(i); window.setTimeout(() => setCopied(null), 1200); } catch { /* sin portapapeles */ }
  };
  const failed = timeline.filter((t) => t.status === "failed" || t.status === "denied").length;
  return (
    <aside className="trail" data-testid="history" aria-label="Estela de tareas">
      <div className="trail-head">
        <h2>ESTELA <span className="count">{all.length} {all.length === 1 ? "tarea" : "tareas"}{failed ? ` · ${failed} con tropiezos` : ""}</span></h2>
        <button onClick={onClose} aria-label="Cerrar la estela" data-testid="history-close">✕</button>
      </div>
      <input className="trail-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Busca entre lo que hemos hecho…" aria-label="Buscar en la estela" />
      <ol>
        {list.map((e) => (
          <li key={e.i} data-testid="history-item">
            <p className="ask">{e.ask}</p>
            {e.answer && <p className="ans">{e.answer}</p>}
            <div className="row">
              <button disabled={disabled} onClick={() => { onRepeat(e.ask); onClose(); }} title="Vuelve a pedírselo a Jarvis">↻ otra vez</button>
              {e.answer && <button onClick={() => void copy(e.i, e.answer!)}>{copied === e.i ? "✓ copiado" : "⧉ copiar respuesta"}</button>}
            </div>
          </li>
        ))}
        {list.length === 0 && <li className="empty">{all.length ? "Nada coincide con esa búsqueda." : EMPTY_TRAIL}</li>}
      </ol>
    </aside>
  );
}
