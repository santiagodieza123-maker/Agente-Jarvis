import { useEffect, useState } from "react";
import { THEMES } from "../themes";
import { ACCENT_COLOR, LIMIT_FIELDS, changed, parseLimits, type LimitField } from "../config";
import type { ConfigSnapshot, HudMessage } from "../events";

const LABEL: Record<LimitField, string> = {
  max_steps: "Pasos máximos por tarea", max_failures: "Fallos acumulados antes de abortar",
  approval_timeout: "Espera de aprobación (s)", token_budget: "Presupuesto de tokens por tarea (0 = sin límite)",
};
const draftOf = (c: ConfigSnapshot) => Object.fromEntries(LIMIT_FIELDS.map((f) => [f, String(c.values[f])])) as Record<LimitField, string>;

export function ConfigPanel({ config, send }: { config: ConfigSnapshot | null; send: (m: HudMessage) => void }) {
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [limits, setLimits] = useState<Record<LimitField, string> | null>(null);
  const [err, setErr] = useState("");
  const sig = config ? JSON.stringify(config.values) : "";
  useEffect(() => { if (config) { setModel(config.values.model); setLimits(draftOf(config)); setErr(""); } }, [sig]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!config || !limits) return <section className="panel"><h2>TALLER</h2><p className="empty">Despertando…</p></section>;

  const k = config.api_key, v = config.values;
  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    const r = parseLimits(limits, config.spec);
    if (!r.ok) { setErr(r.error); return; }
    setErr("");
    const diff = changed(r.values, v as unknown as Record<string, unknown>);
    if (Object.keys(diff).length) send({ type: "config.set", values: diff as Record<string, number> });
  };

  return (
    <section className="panel cfg" data-testid="config-panel">
      <h2>TALLER</h2>

      <h3>El cerebro</h3>
      <form className="row" onSubmit={(e) => { e.preventDefault(); const m = model.trim(); if (m && m !== v.model) send({ type: "config.set", values: { model: m } }); }}>
        <input value={model} onChange={(e) => setModel(e.target.value)} maxLength={64} aria-label="Modelo" data-testid="model" />
        <button disabled={!model.trim() || model.trim() === v.model}>Aplicar</button>
      </form>

      <h3>La llave de Gemini</h3>
      <p className="hint" data-testid="key-status">
        {k.configured ? <>✔ Llave guardada <code>{k.hint}</code> · origen: {k.source}{k.source === "almacén" ? ` (${k.backend})` : ""}</> : <span className="warn">✖ Sin clave: Jarvis no puede razonar</span>}
      </p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (key.trim()) { send({ type: "config.set_api_key", key: key.trim() }); setKey(""); } }}>
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false}
               placeholder="Pega aquí una llave nueva (después no se vuelve a mostrar)" aria-label="Clave de API" data-testid="api-key" />
        <button disabled={!key.trim()}>Guardar</button>
      </form>
      <div className="row">
        <button onClick={() => send({ type: "config.test_llm" })} disabled={!config.llm_ready} data-testid="test-llm">¿Me oyes, Gemini?</button>
        <button className="deny" onClick={() => send({ type: "config.clear_api_key" })} disabled={k.source !== "almacén"} title="Solo quita la guardada desde aquí">Olvidar la llave guardada</button>
      </div>

      <h3>Correas</h3>
      <form className="limits" onSubmit={apply}>
        {LIMIT_FIELDS.map((f) => (
          <label key={f}>
            <span>{LABEL[f]}</span>
            <input inputMode="numeric" value={limits[f]} onChange={(e) => setLimits({ ...limits, [f]: e.target.value })} data-testid={`limit-${f}`} />
          </label>
        ))}
        {err && <p className="warn" role="alert">{err}</p>}
        <button>Ajustar correas</button>
      </form>

      <h3>Color de la esfera</h3>
      <div className="row swatches" role="radiogroup" aria-label="Color">
        {config.accents.map((a) => (
          <button key={a} role="radio" aria-checked={v.accent === a} className={v.accent === a ? "on" : ""} style={{ borderColor: ACCENT_COLOR[a] ?? "#fff" }}
                  onClick={() => send({ type: "config.set", values: { accent: a } })} data-testid={`accent-${a}`}>
            <i style={{ background: ACCENT_COLOR[a] ?? "#fff" }} />{THEMES[a]?.label ?? a}
          </button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={v.browser_headed} onChange={(e) => send({ type: "config.set", values: { browser_headed: e.target.checked } })} data-testid="headed" />
        Mostrar el navegador del agente <em>(al reiniciar)</em>
      </label>

      <label className="check">
        <input type="checkbox" checked={v.confirm_with_extensions !== false} data-testid="confirm-ext"
          onChange={(e) => send({ type: "config.set", values: { confirm_with_extensions: e.target.checked } })} />
        Confirmar las escrituras mientras haya extensiones externas activas <em>(recomendado)</em>
      </label>

      <h3>Lo que hemos gastado</h3>
      <table className="usage" data-testid="usage">
        <thead><tr><th></th><th>llamadas</th><th>entrada</th><th>salida</th></tr></thead>
        <tbody>
          {([["Esta sesión", config.usage], ["Hoy", config.usage.today], ["Total", config.usage.total]] as const).map(([label, b]) =>
            b ? <tr key={label}><td>{label}</td><td>{b.calls.toLocaleString()}</td><td>{b.input.toLocaleString()}</td><td>{b.output.toLocaleString()}</td></tr> : null)}
        </tbody>
      </table>

      <h3>Botón rojo</h3>
      <p className="hint">Frenar todo: <kbd>{config.fixed.kill_hotkey}</kbd> — lo vigila el watchdog, un proceso aparte que ni yo puedo tocar.</p>
    </section>
  );
}
