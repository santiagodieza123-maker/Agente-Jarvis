import { useState } from "react";
import type { Extension, ExtensionsSnapshot, HudMessage } from "../events";

const STATE: Record<string, string> = { stopped: "detenida", starting: "arrancando…", running: "en marcha", error: "error" };
const NAME = /^[a-z][a-z0-9_-]{0,23}$/;

function Ext({ e, send }: { e: Extension; send: (m: HudMessage) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={`ext ${e.state}`} data-testid={`ext-${e.name}`}>
      <div className="row">
        <strong>{e.name}</strong>
        <span className={`badge ${e.state}`} data-testid={`state-${e.name}`}>{STATE[e.state] ?? e.state}</span>
        <span className="grow" />
        <label title="Arranca con Jarvis"><input type="checkbox" checked={e.enabled} data-testid={`enable-${e.name}`}
          onChange={(ev) => send({ type: "extensions.set_enabled", name: e.name, enabled: ev.target.checked })} /> activa</label>
        <button className="small" onClick={() => send({ type: "extensions.restart", name: e.name })}>Reiniciar</button>
        <button className="small deny" data-testid={`remove-${e.name}`}
          onClick={() => { if (window.confirm(`¿Quitar la extensión "${e.name}"?`)) send({ type: "extensions.remove", name: e.name }); }}>Quitar</button>
      </div>
      <code className="cmd">{e.command}</code>
      {e.error && <p className="warn" role="alert">{e.error}</p>}
      {e.tools.length > 0 && (
        <table className="exttools">
          <thead><tr><th>Herramienta</th><th title="Sin pedir confirmación. La salida sigue considerándose no confiable">Lectura</th><th>Usar</th></tr></thead>
          <tbody>
            {e.tools.map((t) => (
              <tr key={t.name} title={t.description}>
                <td><code>{t.raw}</code><small>{t.description.replace(/^\[externa:[^\]]*\]\s*/, "")}</small></td>
                <td><input type="checkbox" checked={t.trusted} aria-label={`${t.raw}: lectura`} data-testid={`trust-${e.name}-${t.raw}`}
                  onChange={(ev) => send({ type: "extensions.set_trust", name: e.name, tool: t.raw, read: ev.target.checked })} /></td>
                <td><input type="checkbox" checked={t.enabled} aria-label={`${t.raw}: usar`}
                  onChange={(ev) => send({ type: "extensions.set_tool", name: e.name, tool: t.raw, enabled: ev.target.checked })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button className="small" onClick={() => setOpen(!open)}>{open ? "Ocultar registro" : "Ver registro"}</button>
      {open && <pre className="extlog" data-testid={`log-${e.name}`}>{e.log || "(sin salida de error)"}</pre>}
    </li>
  );
}

export function ExtensionsPanel({ ext, send }: { ext: ExtensionsSnapshot | null; send: (m: HudMessage) => void }) {
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  if (!ext) return <section className="panel"><h2>EXTENSIONES (MCP)</h2><p className="empty">Cargando…</p></section>;
  const valid = NAME.test(name) && command.trim().length > 0;
  const add = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!valid) return;
    const ok = window.confirm(`Jarvis ejecutará este programa en tu equipo, con tus permisos:\n\n${command.trim()}\n\n¿Confías en él?`);
    if (!ok) return;
    send({ type: "extensions.add", name, command: command.trim(), confirmed: true });
    setName(""); setCommand("");
  };
  return (
    <section className="panel exts" data-testid="extensions-panel">
      <h2>EXTENSIONES (MCP)</h2>
      <p className="hint">Servidores MCP por stdio. Sus herramientas piden confirmación siempre, salvo las que marques como «lectura», y su salida se trata como no confiable.</p>
      <ul>
        {ext.extensions.map((e) => <Ext key={e.name} e={e} send={send} />)}
        {!ext.extensions.length && <li className="empty">Ninguna extensión instalada</li>}
      </ul>
      <h3>Añadir</h3>
      <form className="addext" onSubmit={add}>
        <input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="nombre (a-z, 0-9, - _)" maxLength={24} aria-label="Nombre" data-testid="ext-name" />
        <input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="comando, p. ej.: npx -y @modelcontextprotocol/server-everything" maxLength={1000} aria-label="Comando" data-testid="ext-command" />
        <button disabled={!valid || ext.extensions.length >= ext.limits.extensions} data-testid="ext-add">Añadir</button>
      </form>
    </section>
  );
}
