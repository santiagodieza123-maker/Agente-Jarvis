import { useState } from "react";
import { parseEnvLines } from "../config";
import type { Extension, ExtensionsSnapshot, HudMessage } from "../events";

const STATE: Record<string, string> = { stopped: "detenida", starting: "arrancando…", running: "en marcha", error: "error" };
const NAME = /^[a-z][a-z0-9_-]{0,23}$/;

function EnvEditor({ e, send }: { e: Extension; send: (m: HudMessage) => void }) {
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const names = e.env_names ?? [];
  const save = (ev: React.FormEvent) => {
    ev.preventDefault();
    const r = parseEnvLines(text);
    if (!r.ok) { setErr(r.error); return; }
    setErr(""); setText("");
    send({ type: "extensions.set_env", name: e.name, env: r.env });
  };
  return (
    <details className="envbox">
      <summary>Variables de entorno ({names.length})</summary>
      <p className="hint">{names.length ? names.map((n) => <code key={n}>{n}=•••</code>) : "Ninguna"} — los valores no se muestran nunca. Guardar reemplaza todas y reinicia la extensión.</p>
      <form onSubmit={save}>
        <textarea value={text} onChange={(ev) => setText(ev.target.value)} rows={3} spellCheck={false} placeholder={"NOMBRE=valor\nOTRA=valor"} aria-label={`Variables de ${e.name}`} data-testid={`env-${e.name}`} />
        {err && <p className="warn" role="alert">{err}</p>}
        <button className="small" disabled={!text.trim() && names.length === 0}>{text.trim() ? "Guardar variables" : "Quitar todas"}</button>
      </form>
    </details>
  );
}

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
      <EnvEditor e={e} send={send} />
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
  const [envText, setEnvText] = useState("");
  const [envErr, setEnvErr] = useState("");
  if (!ext) return <section className="panel"><h2>INJERTOS (MCP)</h2><p className="empty">Despertando…</p></section>;
  const valid = NAME.test(name) && command.trim().length > 0;
  const add = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!valid) return;
    const r = parseEnvLines(envText);
    if (!r.ok) { setEnvErr(r.error); return; }
    setEnvErr("");
    const vars = Object.keys(r.env);
    const ok = window.confirm(`Jarvis ejecutará este programa en tu equipo, con tus permisos:\n\n${command.trim()}` +
      (vars.length ? `\n\ncon las variables: ${vars.join(", ")}` : "") + "\n\n¿Confías en él?");
    if (!ok) return;
    send(vars.length ? { type: "extensions.add", name, command: command.trim(), confirmed: true, env: r.env } : { type: "extensions.add", name, command: command.trim(), confirmed: true });
    setName(""); setCommand(""); setEnvText("");
  };
  return (
    <section className="panel exts" data-testid="extensions-panel">
      <h2>INJERTOS (MCP)</h2>
      <p className="hint">Poderes extra que le enchufas a Jarvis (servidores MCP). Sus herramientas piden confirmación siempre, salvo las que marques como «lectura», y su salida se trata como no confiable.</p>
      <ul>
        {ext.extensions.map((e) => <Ext key={e.name} e={e} send={send} />)}
        {!ext.extensions.length && <li className="empty">Nada injertado todavía</li>}
      </ul>
      <h3>Injertar uno nuevo</h3>
      <form className="addext" onSubmit={add}>
        <input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="nombre (a-z, 0-9, - _)" maxLength={24} aria-label="Nombre" data-testid="ext-name" />
        <input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="comando, p. ej.: npx -y @modelcontextprotocol/server-everything" maxLength={1000} aria-label="Comando" data-testid="ext-command" />
        <textarea value={envText} onChange={(e) => setEnvText(e.target.value)} rows={2} spellCheck={false} placeholder={"Variables de entorno (opcional), una por línea: NOMBRE=valor"} aria-label="Variables de entorno" data-testid="ext-env" />
        {envErr && <p className="warn" role="alert">{envErr}</p>}
        <button disabled={!valid || ext.extensions.length >= ext.limits.extensions} data-testid="ext-add">Añadir</button>
      </form>
    </section>
  );
}
