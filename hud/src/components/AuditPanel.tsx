import { useEffect, useState } from "react";
import { brief, severity, type AuditSnapshot, type AuditVerified } from "../audit";
import type { HudMessage } from "../events";

const fmt = (ts: number) => (ts ? new Date(ts * 1000).toLocaleTimeString() : "—");

function Status({ v, total }: { v: AuditVerified | null; total: number }) {
  if (!v) return <span className="vstat" data-testid="verify-status">Sin verificar</span>;
  if (!v.ok) return <span className="vstat bad" data-testid="verify-status">✖ CADENA ROTA {v.bad_line ? `en la línea ${v.bad_line}` : v.reason ? `(${v.reason})` : ""} ({v.count} registros válidos antes)</span>;
  const later = total - v.count;
  return <span className="vstat good" data-testid="verify-status">✔ Cadena íntegra{v.keyed ? " y autenticada (HMAC)" : " (sin clave: no detecta una reescritura completa)"} · {v.count} registros{later > 0 ? ` (+${later} posteriores sin verificar)` : ""}</span>;
}

export function AuditPanel({ audit, verified, send }: { audit: AuditSnapshot | null; verified: AuditVerified | null; send: (m: HudMessage) => void }) {
  const [event, setEvent] = useState("");
  const [text, setText] = useState("");
  const query = (e = event, t = text) => send({ type: "audit.get", limit: 200, event: e, text: t });
  useEffect(() => { query(); /* carga inicial al abrir la pestaña */ }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const exportJson = () => send({ type: "audit.export", ...(audit?.filters.event ? { event: audit.filters.event } : {}), ...(audit?.filters.text ? { text: audit.filters.text } : {}) });

  if (!audit) return <section className="panel"><h2>AUDITORÍA</h2><p className="empty">Cargando…</p></section>;
  return (
    <section className="panel audit" data-testid="audit-panel">
      <h2>AUDITORÍA <span className="count">{audit.matched}/{audit.total}</span></h2>
      <div className="row">
        <Status v={verified} total={audit.total} />
        <button onClick={() => send({ type: "audit.verify" })} data-testid="verify-btn">Verificar cadena</button>
      </div>
      <p className="hint">
        Cabecera <code title={audit.head} data-testid="audit-head">{audit.head.slice(0, 12)}…</code> — anótala aparte: detecta ediciones y borrados,
        pero no una reescritura completa del archivo.{audit.truncated && " Solo se muestra el final de un log muy grande."}
      </p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); query(); }}>
        <select value={event} aria-label="Filtrar por evento" onChange={(e) => { setEvent(e.target.value); query(e.target.value, text); }}>
          <option value="">todos los eventos</option>
          {audit.event_types.map((t) => <option key={t}>{t}</option>)}
        </select>
        <input value={text} maxLength={100} onChange={(e) => setText(e.target.value)} placeholder="Buscar en los datos…" aria-label="Buscar" />
        <button>Buscar</button>
        <button type="button" onClick={() => query()} title="Recargar">↻</button>
        <button type="button" onClick={exportJson} disabled={!audit.records.length} title="Guarda en ~/.jarvis/exports/ todos los registros que cumplan el filtro actual (completos, en JSONL)">Exportar</button>
      </form>
      <ul className="auditlist">
        {audit.records.map((r) => (
          <li key={r.seq} data-testid="audit-row">
            <details>
              <summary>
                <span className="seq">#{r.seq}</span><span className="time">{fmt(r.ts)}</span>
                <span className={`evt ${severity(r.event)}`}>{r.event}</span><span className="brief">{brief(r)}</span>
              </summary>
              <pre>{JSON.stringify(r.data, null, 2)}{r.clipped ? "\n(recortado: el log en disco lo conserva completo)" : ""}</pre>
              <code className="hashes">prev {r.prev.slice(0, 12)}… → hash {r.hash.slice(0, 12)}…</code>
            </details>
          </li>
        ))}
        {!audit.records.length && <li className="empty">Sin registros que coincidan</li>}
      </ul>
    </section>
  );
}
