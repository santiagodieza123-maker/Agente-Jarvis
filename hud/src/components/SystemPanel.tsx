import type { Stats } from "../events";

function Spark({ values, max, label }: { values: number[]; max?: number; label: string }) {
  if (values.length < 2) return <svg className="spark" viewBox="0 0 120 28" aria-label={label} />;
  const hi = Math.max(max ?? 0, ...values, 1);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 120},${27 - (Math.min(v, hi) / hi) * 26}`).join(" ");
  return <svg className="spark" viewBox="0 0 120 28" preserveAspectRatio="none" role="img" aria-label={label}><polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" /></svg>;
}

const mb = (b: number) => `${(b / 1048576).toFixed(0)} MB`;
const dur = (s: number) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
const DOT: Record<string, string> = { ok: "ok", arrancando: "warn", aviso: "warn", "sin clave": "warn", error: "bad", inactivo: "off", "no disponible": "off" };

function Tile({ title, value, sub, values, max, testid }: { title: string; value: string; sub?: string; values: number[]; max?: number; testid: string }) {
  return (
    <div className="tile" data-testid={testid}>
      <span className="tt">{title}</span><b>{value}</b><small>{sub ?? " "}</small>
      <Spark values={values} max={max} label={`Evolución de ${title}`} />
    </div>
  );
}

export function SystemPanel({ stats }: { stats: Stats[] }) {
  const s = stats[stats.length - 1];
  if (!s) return <section className="panel sys" data-testid="system-panel"><h2>PULSO</h2><p className="empty">Tomando el pulso…</p></section>;
  const lat = stats.map((x) => x.llm.last_ms ?? 0);
  return (
    <section className="panel sys" data-testid="system-panel">
      <h2>PULSO <span className="count">en marcha {dur(s.uptime)} · {s.clients} HUD</span></h2>
      <div className="tiles">
        <Tile testid="tile-cpu" title="CPU del núcleo" value={`${s.cpu.process.toFixed(0)} %`} sub={`sistema ${s.cpu.system.toFixed(0)} % · ${s.cpu.cores} núcleos`} values={stats.map((x) => x.cpu.process)} max={100} />
        <Tile testid="tile-mem" title="Memoria del núcleo" value={mb(s.memory.rss)} sub={`sistema ${s.memory.system_percent.toFixed(0)} % · ${s.threads} hilos`} values={stats.map((x) => x.memory.rss)} />
        <Tile testid="tile-lag" title="Retardo del bucle" value={`${s.loop_lag_ms.toFixed(0)} ms`} sub={s.loop_lag_ms > 100 ? "⚠ el núcleo va lento" : "fluido"} values={stats.map((x) => x.loop_lag_ms)} max={50} />
        <Tile testid="tile-llm" title="Latencia del modelo" value={s.llm.last_ms !== null ? `${s.llm.last_ms} ms` : "—"} sub={s.llm.avg_ms !== null ? `media ${s.llm.avg_ms} · p95 ${s.llm.p95_ms} ms` : "sin llamadas"} values={lat} />
      </div>
      <p className="hint" data-testid="llm-line">Modelo {s.llm.model ?? "—"} · {s.llm.calls} llamadas · {s.llm.errors} errores</p>
      {s.gpu && (
        <div className="gpu" data-testid="gpu"><span>{s.gpu.name}</span>
          <div className="bar" title="Uso de la GPU"><i style={{ width: `${Math.min(100, s.gpu.util)}%` }} /></div><em>{s.gpu.util.toFixed(0)} %</em>
          <div className="bar" title="Memoria de vídeo"><i style={{ width: `${Math.min(100, (100 * s.gpu.mem_used) / (s.gpu.mem_total || 1))}%` }} /></div><em>{s.gpu.mem_used.toFixed(0)}/{s.gpu.mem_total.toFixed(0)} MB</em></div>
      )}
      <h3>Órganos</h3>
      <ul className="comps">
        {s.components.map((c) => (
          <li key={c.name} data-testid={`comp-${c.name}`}><i className={`dot ${DOT[c.state] ?? "warn"}`} /><b>{c.name}</b><span>{c.state}</span><small>{c.detail}</small></li>
        ))}
      </ul>
      <h3>Criaturas lanzadas ({s.children.length})</h3>
      <table className="kids"><tbody>
        {s.children.map((k) => <tr key={k.pid}><td>{k.name}</td><td>{k.pid}</td><td>{k.cpu.toFixed(0)} %</td><td>{mb(k.rss)}</td></tr>)}
        {!s.children.length && <tr><td className="empty">Ninguna (navegador, shell y extensiones duermen)</td></tr>}
      </tbody></table>
    </section>
  );
}
