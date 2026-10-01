// Lógica pura del panel de auditoría (probada en audit.test.ts).
export interface AuditRecord {
  seq: number; ts: number; event: string; data: Record<string, unknown>; prev: string; hash: string; clipped?: boolean;
}
export interface AuditFilters { event: string; text: string; limit: number }
export interface AuditSnapshot {
  records: AuditRecord[]; matched: number; total: number; event_types: string[]; head: string; truncated: boolean; filters: AuditFilters;
}
export interface AuditVerified { ok: boolean; count: number; bad_line: number | null; head: string; keyed?: boolean; reason?: string | null }

export function asAudit(p: Record<string, unknown>): AuditSnapshot | null {
  return Array.isArray(p.records) && Array.isArray(p.event_types) && typeof p.filters === "object" && p.filters !== null
    && typeof p.total === "number" && typeof p.head === "string" ? (p as unknown as AuditSnapshot) : null;
}
export function asVerified(p: Record<string, unknown>): AuditVerified | null {
  return typeof p.ok === "boolean" && typeof p.count === "number" ? (p as unknown as AuditVerified) : null;
}
export function asRecord(p: Record<string, unknown>): AuditRecord | null {
  return typeof p.seq === "number" && typeof p.event === "string" && typeof p.hash === "string" && typeof p.data === "object" && p.data !== null
    ? (p as unknown as AuditRecord) : null;
}

/** Misma regla que el servidor: evento exacto y texto sin distinguir mayúsculas en el evento o en los datos. */
export function matches(r: AuditRecord, f: AuditFilters): boolean {
  if (f.event && r.event !== f.event) return false;
  if (f.text) {
    const n = f.text.toLowerCase();
    if (!r.event.toLowerCase().includes(n) && !JSON.stringify(r.data).toLowerCase().includes(n)) return false;
  }
  return true;
}

export type Severity = "bad" | "warn" | "info" | "good" | "neutral";
export function severity(event: string): Severity {
  if (/denied|rejected|aborted|crashed|kill|corrupt|tamper/.test(event)) return "bad";
  if (event.startsWith("approval") || event.startsWith("permissions.")) return "warn";
  if (event.startsWith("task.")) return "info";
  if (event === "action.finished" || event.startsWith("memory.")) return "good";
  return "neutral";
}

export function brief(r: AuditRecord): string {
  const d = r.data, pick = d.tool ?? d.goal ?? d.status ?? d.reason ?? d.error ?? d.kind ?? d.path ?? d.port;
  const s = pick !== undefined ? String(pick) : JSON.stringify(d);
  return s.length > 90 ? s.slice(0, 90) + "…" : s;
}

export const MAX_ROWS = 500;
