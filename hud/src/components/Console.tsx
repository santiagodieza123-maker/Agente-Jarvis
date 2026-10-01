import { useEffect, useRef, useState } from "react";
import type { HudState } from "../store";

export function Console({ chat, disabled, onSubmit }: { chat: HudState["chat"]; disabled: boolean; onSubmit: (t: string) => void }) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [chat.length]);
  return (
    <section className="panel console">
      <h2>CABINA DE MANDO</h2>
      <div className="log">
        {chat.map((m, i) => <p key={i} className={m.who}><b>{m.who === "user" ? "TÚ" : "J."}</b> {m.text}</p>)}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (t) { onSubmit(t); setText(""); } }}>
        <input value={text} onChange={(e) => setText(e.target.value)} disabled={disabled} placeholder={disabled ? "el núcleo duerme; espera a que despierte…" : "¿Qué hacemos hoy, jefe?"} />
      </form>
    </section>
  );
}
