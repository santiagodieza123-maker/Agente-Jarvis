import { useState } from "react";
import type { BrokerSnapshot, HudMessage, PermissionsSnapshot } from "../events";

const LABEL: Record<string, string> = {
  read: "Lectura", write_reversible: "Escritura reversible", destructive: "Destructiva", elevated: "Elevada",
};

function Broker({ b, send }: { b: BrokerSnapshot | null; send: (m: HudMessage) => void }) {
  const [svc, setSvc] = useState("");
  if (!b) return null;
  return (
    <div className="broker" data-testid="broker">
      <h3>Manos de administrador</h3>
      <p className="hint" data-testid="broker-state">
        {!b.available ? "No disponible: solo existe en Windows."
          : b.running ? <>✔ En marcha{b.elevated ? " con privilegios de administrador" : " (SIN elevar: las operaciones fallarán)"}{b.dry_run ? " · modo simulación" : ""} · pid {b.pid}</>
          : <>Detenido. {b.error && <span className="warn">{b.error}</span>}</>}
      </p>
      {b.available && (
        <>
          <div className="row">
            {!b.running
              ? <button onClick={() => send({ type: "broker.start" })} data-testid="broker-start" title="Windows mostrará su aviso de UAC: solo tú puedes aceptarlo">Iniciar (pedirá UAC)</button>
              : <button className="deny" onClick={() => send({ type: "broker.stop" })} data-testid="broker-stop">Detener</button>}
          </div>
          {b.running && (
            <>
              <p className="hint">Servicios que Jarvis puede controlar: {b.services?.length ? b.services.map((s) => <code key={s}>{s} </code>) : "ninguno"}</p>
              <form className="row" onSubmit={(e) => { e.preventDefault(); const n = svc.trim(); if (n) { send({ type: "broker.allow_service", name: n }); setSvc(""); } }}>
                <input value={svc} onChange={(e) => setSvc(e.target.value)} placeholder="Permitir un servicio (p. ej. Spooler)…" aria-label="Servicio" data-testid="broker-svc" />
                <button disabled={!svc.trim()}>Permitir</button>
              </form>
            </>
          )}
          <p className="hint">Solo hay dos operaciones: instalar con winget y controlar servicios permitidos. Cada una pide tu confirmación en el HUD <b>y</b> otra en una ventana propia del broker, que el agente no puede pulsar.</p>
        </>
      )}
    </div>
  );
}

export function PermissionsPanel({ perms, broker, send }: { perms: PermissionsSnapshot | null; broker: BrokerSnapshot | null; send: (m: HudMessage) => void }) {
  const [root, setRoot] = useState("");
  if (!perms) return <section className="panel"><h2>LLAVES</h2><p className="empty">Despertando…</p></section>;

  return (
    <section className="panel perms" data-testid="permissions-panel">
      <h2>LLAVES</h2>
      <label className="grow" title="Sin confirmaciones y acceso a todos tus archivos (salvo los secretos de Jarvis)">
        <input type="checkbox" checked={!!perms.autonomous} data-testid="autonomous"
               onChange={(e) => {
                 if (e.target.checked && !window.confirm("Modo autónomo: Jarvis hará TODO sin preguntarte, incluso borrar archivos y acciones de administrador, también si una web le da instrucciones. ¿Activar?")) return;
                 send({ type: "permissions.set_autonomous", value: e.target.checked });
               }} />
        Modo autónomo (no preguntar nunca, todos los archivos)
      </label>
      <h3>Antes de hacer esto, pregúntame…</h3>
      <ul>
        {perms.classes.map((c) => (
          <li key={c.name}>
            <label className="grow">
              <input type="checkbox" checked={c.confirm} disabled={c.locked} data-testid={`confirm-${c.name}`}
                     onChange={(e) => send({ type: "permissions.set_confirm", class: c.name, value: e.target.checked })} />
              {LABEL[c.name] ?? c.name}
            </label>
            {c.locked && <em title="No se puede desactivar">🔒 siempre</em>}
          </li>
        ))}
      </ul>
      <h3>Qué sabe hacer</h3>
      <ul>
        {perms.tools.map((t) => (
          <li key={t.name}>
            <label className="grow" title={t.description}>
              <input type="checkbox" checked={t.enabled} data-testid={`tool-${t.name}`}
                     onChange={(e) => send({ type: "permissions.set_tool", tool: t.name, enabled: e.target.checked })} />
              <code>{t.name}</code>
            </label>
            <em>{LABEL[t.cls] ?? t.cls}</em>
          </li>
        ))}
      </ul>
      <h3>Dónde puede meter mano</h3>
      <ul>
        {perms.roots.map((r) => (
          <li key={r} data-testid="root">
            <code className="grow">{r}</code>
            <button className="deny" onClick={() => send({ type: "permissions.remove_root", path: r })} aria-label={`Quitar ${r}`}>Quitar</button>
          </li>
        ))}
        {!perms.roots.length && <li className="empty">Ninguna: Jarvis no puede tocar un solo archivo</li>}
      </ul>
      <form className="row" onSubmit={(e) => { e.preventDefault(); const t = root.trim(); if (t) { send({ type: "permissions.add_root", path: t }); setRoot(""); } }}>
        <input value={root} onChange={(e) => setRoot(e.target.value)} placeholder="Ruta completa de una carpeta que le prestas…" aria-label="Nueva carpeta" />
        <button disabled={!root.trim()}>Añadir</button>
      </form>
      <Broker b={broker} send={send} />
    </section>
  );
}
