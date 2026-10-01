import { useState } from "react";
import type { Frame } from "../events";

const COLOR: Record<string, string> = { button: "#ff9f1a", edit: "#35e08a", checkbox: "#c58aff", radiobutton: "#c58aff", combobox: "#2fb8ff", hyperlink: "#2fb8ff", menuitem: "#ffd23f", tabitem: "#ffd23f", listitem: "#ff6b9d" };

export function VisionPanel({ frame }: { frame: Frame | null }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!frame) return <section className="panel vision" data-testid="vision-panel"><h2>VISIÓN DEL AGENTE</h2><p className="empty">Todavía no ha mirado ninguna ventana. Cuando Jarvis use las herramientas gui.*, verás aquí su captura con los elementos numerados.</p></section>;
  const focus = frame.highlight ?? hover;
  const items = frame.elements.filter((e) => e.interactive);
  return (
    <section className="panel vision" data-testid="vision-panel">
      <h2>VISIÓN DEL AGENTE <span className="count">{frame.title || "—"} · #{frame.seq}</span></h2>
      {frame.action && <p className="hint" data-testid="vision-action">▶ {frame.action}</p>}
      <div className="shot">
        <img src={`data:image/jpeg;base64,${frame.image}`} alt={`Captura de ${frame.title}`} width={frame.width} height={frame.height} draggable={false} />
        <svg viewBox={`0 0 ${frame.width} ${frame.height}`} preserveAspectRatio="xMinYMin meet" aria-hidden="true">
          {items.map((e) => {
            const [l, t, r, b] = e.rect, hot = focus === e.id;
            return (
              <g key={e.id} data-testid={`box-${e.id}`} className={hot ? "hot" : ""} onMouseEnter={() => setHover(e.id)} onMouseLeave={() => setHover(null)}>
                <rect x={l} y={t} width={Math.max(0, r - l)} height={Math.max(0, b - t)} fill={hot ? "rgba(255,45,85,.18)" : "transparent"} stroke={hot ? "#ff2d55" : COLOR[e.role] ?? "#fff"} strokeWidth={hot ? 3 : 1.5} opacity={e.enabled ? 1 : 0.4} />
                <rect x={l} y={Math.max(0, t - 14)} width={String(e.id).length * 8 + 6} height={14} fill={hot ? "#ff2d55" : COLOR[e.role] ?? "#fff"} />
                <text x={l + 3} y={Math.max(11, t - 3)} fontSize="11" fill="#000" fontWeight="bold">{e.id}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <ul className="elist">
        {items.map((e) => (
          <li key={e.id} className={focus === e.id ? "on" : ""} onMouseEnter={() => setHover(e.id)} onMouseLeave={() => setHover(null)}>
            <b>{e.id}</b> <span>{e.role}</span> {e.name || <em>(sin nombre)</em>}{!e.enabled && " (deshabilitado)"}
          </li>
        ))}
        {!items.length && <li className="empty">Sin elementos interactivos en esta captura</li>}
      </ul>
    </section>
  );
}
