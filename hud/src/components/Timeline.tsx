import type { TimelineItem } from "../store";

export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <section className="panel timeline">
      <h2>RASTRO</h2>
      <ul>
        {[...items].reverse().map((t) => (
          <li key={t.id} className={t.status}>
            <span className="dot" />{t.tool}<em>{t.status}</em>
          </li>
        ))}
        {items.length === 0 && <li className="empty">Todo en calma</li>}
      </ul>
    </section>
  );
}
