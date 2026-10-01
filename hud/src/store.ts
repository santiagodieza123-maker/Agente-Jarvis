import { MAX_ROWS, asAudit, mergeRecent, asRecord, asVerified, matches, type AuditRecord, type AuditSnapshot, type AuditVerified } from "./audit";
import { asConfig, asExtensions, asFrame, asMemory, asStats, asPermissions, type ConfigSnapshot, type ExtensionsSnapshot, type Frame, type JarvisEvent, type Stats, type MemorySnapshot, type PermissionsSnapshot } from "./events";

export type AgentState = "idle" | "thinking" | "acting" | "awaiting" | "error" | "killed";
export type Conn = "connecting" | "open" | "closed";

export interface TimelineItem {
  id: number;
  ts: number;
  tool: string;
  status: "running" | "ok" | "failed" | "denied";
}
export interface Approval { id: string; tool: string; args: unknown; origin: string; why?: string; warnings?: string[] }

export interface HudState {
  conn: Conn;
  agent: AgentState;
  plan: string;
  timeline: TimelineItem[];
  approvals: Approval[];
  chat: { who: "user" | "jarvis"; text: string }[];
  memory: MemorySnapshot | null;
  permissions: PermissionsSnapshot | null;
  config: ConfigSnapshot | null;
  extensions: ExtensionsSnapshot | null;
  stats: Stats[];                 // últimas muestras del sistema (para los gráficos)
  frame: Frame | null;            // última captura que «ve» el agente
  notice: { level: string; text: string; id: number } | null;
  audit: AuditSnapshot | null;
  auditVerified: AuditVerified | null;
  recent: AuditRecord[];          // últimos registros recibidos en vivo: cubren la carrera con una consulta en curso
}

export const initial: HudState = { conn: "connecting", agent: "idle", plan: "", timeline: [], approvals: [], chat: [], memory: null, permissions: null, config: null, extensions: null, frame: null, stats: [], notice: null, audit: null, auditVerified: null, recent: [] };

export type Action =
  | { kind: "conn"; conn: Conn }
  | { kind: "event"; event: JarvisEvent }
  | { kind: "user"; text: string }
  | { kind: "clear_notice"; id: number };

const MAX_TIMELINE = 200;
const MAX_STATS = 60;
let seq = 0;

export function reduce(s: HudState, a: Action): HudState {
  if (a.kind === "conn") {
    const agent = a.conn === "closed" && s.agent !== "killed" ? "error" : a.conn === "open" && s.agent === "error" ? "idle" : s.agent;
    return { ...s, conn: a.conn, agent };
  }
  if (a.kind === "clear_notice") return s.notice?.id === a.id ? { ...s, notice: null } : s;
  if (a.kind === "user") return { ...s, chat: [...s.chat, { who: "user", text: a.text }] };

  const { type, payload: p } = a.event;
  const tool = String(p.tool ?? "?");
  switch (type) {
    case "state.changed": {
      const st = p.state;
      return st === "idle" || st === "thinking" ? { ...s, agent: st } : s;
    }
    case "plan.updated": {
      const text = String(p.text ?? "");
      return { ...s, plan: text, agent: "thinking", chat: text ? [...s.chat, { who: "jarvis", text }] : s.chat };
    }
    case "action.started":
      return { ...s, agent: "acting", timeline: [...s.timeline, { id: ++seq, ts: a.event.ts, tool, status: "running" as const }].slice(-MAX_TIMELINE) };
    case "action.finished": {
      const i = [...s.timeline].reverse().findIndex((t) => t.tool === tool && t.status === "running");
      const idx = i < 0 ? -1 : s.timeline.length - 1 - i;
      const timeline = s.timeline.map((t, k) => (k === idx ? { ...t, status: p.ok ? "ok" as const : "failed" as const } : t));
      return { ...s, timeline, agent: "thinking" };
    }
    case "approval.requested":
      return { ...s, agent: "awaiting", approvals: [...s.approvals, { id: String(p.id ?? tool), tool, args: p.args, origin: String(p.origin ?? ""), why: String(p.why ?? ""), warnings: Array.isArray(p.warnings) ? p.warnings.map(String).slice(0, 6) : [] }] };
    case "approval.granted":
    case "approval.denied": {
      const denied = type === "approval.denied";
      const approvals = s.approvals.filter((x) => (p.id !== undefined ? x.id !== String(p.id) : x.tool !== tool));
      const timeline = denied ? [...s.timeline, { id: ++seq, ts: a.event.ts, tool, status: "denied" as const }].slice(-MAX_TIMELINE) : s.timeline;
      return { ...s, approvals, timeline, agent: approvals.length ? "awaiting" : "thinking" };
    }
    case "memory.changed":
      return { ...s, memory: asMemory(p) ?? s.memory };
    case "permissions.changed":
      return { ...s, permissions: asPermissions(p) ?? s.permissions };
    case "config.changed":
      return { ...s, config: asConfig(p) ?? s.config };
    case "system.stats": {
      const st = asStats(p);
      return st ? { ...s, stats: [...s.stats, st].slice(-MAX_STATS) } : s;
    }
    case "perception.frame":
      return { ...s, frame: asFrame(p) ?? s.frame };
    case "extensions.changed":
      return { ...s, extensions: asExtensions(p) ?? s.extensions };
    case "audit.changed": {
      const snap = asAudit(p);
      return { ...s, audit: snap ? mergeRecent(snap, s.recent) : s.audit };
    }
    case "audit.verified":
      return { ...s, auditVerified: asVerified(p) ?? s.auditVerified };
    case "audit.appended": {            // registro en vivo: solo si el panel ya cargó y el registro cumple el filtro actual
      const r = asRecord(p), a = s.audit;
      if (!r) return s;
      const recent = [...s.recent.filter((x) => x.seq !== r.seq), r].slice(-50);
      if (!a || a.records.some((x) => x.seq === r.seq)) return { ...s, recent };
      const types = a.event_types.includes(r.event) ? a.event_types : [...a.event_types, r.event].sort();
      const show = matches(r, a.filters);
      return { ...s, recent, audit: { ...a, total: a.total + 1, head: r.hash, event_types: types,
        matched: a.matched + (show ? 1 : 0), records: show ? [r, ...a.records].slice(0, Math.min(a.filters.limit, MAX_ROWS)) : a.records } };
    }
    case "ui.notice":
      return { ...s, notice: { level: String(p.level ?? "info"), text: String(p.text ?? "").slice(0, 300), id: ++seq } };
    case "kill.triggered":
      return { ...s, agent: "killed", approvals: [], frame: null };
    default:
      return s;
  }
}
