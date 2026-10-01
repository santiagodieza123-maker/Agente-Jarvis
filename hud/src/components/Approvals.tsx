import type { Approval } from "../store";

export function Approvals({ items, onDecide }: { items: Approval[]; onDecide: (a: Approval, granted: boolean) => void }) {
  if (!items.length) return null;
  return (
    <section className="panel approvals" role="alertdialog" aria-label="Aprobación requerida">
      <h2>ALTO: NECESITO TU PERMISO</h2>
      {items.map((a) => (
        <div key={a.id} className="req">
          <code>{a.tool}</code>
          {a.origin === "observed" && <strong className="warn"> ⚠ {a.why === "extensions" ? "hay extensiones externas activas: confirma las escrituras" : "originada tras leer contenido no confiable"}</strong>}
          {!!a.warnings?.length && <p className="danger" role="alert" data-testid="approval-warning">🛑 Toca {a.warnings.join(", ")}. Revisa el comando antes de permitir.</p>}
          <pre>{JSON.stringify(a.args, null, 2)}</pre>
          <button onClick={() => onDecide(a, true)}>Permitir</button>
          <button className="deny" onClick={() => onDecide(a, false)}>Denegar</button>
        </div>
      ))}
    </section>
  );
}
