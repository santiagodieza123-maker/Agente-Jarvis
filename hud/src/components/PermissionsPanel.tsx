import { useState } from "react";
import type { HudMessage, PermissionsSnapshot } from "../events";

const LABEL: Record<string, string> = {
  read: "Lectura", write_reversible: "Escritura reversible", destructive: "Destructiva", elevated: "Elevada",
};

export function PermissionsPanel({ perms, send }: { perms: PermissionsSnapshot | null; send: (m: HudMessage) => void }) {
  const [root, setRoot] = useState("");
  if (!perms) return <section className="panel"><h2>PERMISOS</h2><p className="empty">Cargando…</p></section>;

  return (
    <section className="panel perms" data-testid="permissions-panel">
      <h2>PERMISOS</h2>
      <h3>Pedir confirmación antes de…</h3>
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
      <h3>Herramientas</h3>
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
      <h3>Carpetas accesibles</h3>
      <ul>
        {perms.roots.map((r) => (
          <li key={r} data-testid="root">
            <code className="grow">{r}</code>
            <button className="deny" onClick={() => send({ type: "permissions.remove_root", path: r })} aria-label={`Quitar ${r}`}>Quitar</button>
          </li>
        ))}
        {!perms.roots.length && <li className="empty">Ninguna: Jarvis no puede leer ni escribir archivos</li>}
      </ul>
      <form className="row" onSubmit={(e) => { e.preventDefault(); const t = root.trim(); if (t) { send({ type: "permissions.add_root", path: t }); setRoot(""); } }}>
        <input value={root} onChange={(e) => setRoot(e.target.value)} placeholder="Ruta absoluta de una carpeta…" aria-label="Nueva carpeta" />
        <button disabled={!root.trim()}>Añadir</button>
      </form>
    </section>
  );
}
