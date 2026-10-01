import { MAX_ROWS, asAudit, asRecord, asVerified, matches, type AuditSnapshot, type AuditVerified } from "./audit";
import { asConfig, asExtensions, asMemory, asPermissions, type ConfigSnapshot, type ExtensionsSnapshot, type JarvisEvent, type MemorySnapshot, type PermissionsSnapshot } from "./events";

export type AgentState = "idle" | "thinking" | "acting" | "awaiting" | "error" | "killed";
export type Conn = "connecting" | "open" | "closed";

export interface TimelineItem {
  id: number;
  ts: number;
  tool: string;
  status: "running" | "ok" | "failed" | "denied";
}
export interface Approval { id: string; tool: string; args: unknown; origin: string; why?: string }

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
  notice: { level: string; text: string; id: number } | null;
  audit: AuditSnapshot | null;
  auditVerified: AuditVerified | null;
}

export const initial: HudState = { conn: "connecting", agent: "idle", plan: "", timeline: [], approvals: [], chat: [], memory: null, permissions: null, config: null, extensions: null, notice: null, audit: null, auditVerified: null };

export type Action =
  | { kind: "conn"; conn: Conn }
  | { kind: "event"; event: JarvisEvent }
  | { kind: "user"; text: string }
  | { kind: "clear_notice"; id: number };

const MAX_TIMELINE = 200;
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
      return { ...s, agent: "awaiting", approvals: [...s.approvals, { id: String(p.id ?? tool), tool, args: p.args, origin: String(p.origin ?? ""), why: String(p.why ?? "") }] };
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
    case "extensions.changed":
      return { ...s, extensions: asExtensions(p) ?? s.extensions };
    case "audit.changed":
      return { ...s, audit: asAudit(p) ?? s.audit };
    case "audit.verified":
      return { ...s, auditVerified: asVerified(p) ?? s.auditVerified };
    case "audit.appended": {            // registro en vivo: solo si el panel ya cargó y el registro cumple el filtro actual
      const r = asRecord(p), a = s.audit;
      if (!r || !a || a.records.some((x) => x.seq === r.seq)) return s;
      const types = a.event_types.includes(r.event) ? a.event_types : [...a.event_types, r.event].sort();
      const show = matches(r, a.filters);
      return { ...s, audit: { ...a, total: a.total + 1, head: r.hash, event_types: types,
        matched: a.matched + (show ? 1 : 0), records: show ? [r, ...a.records].slice(0, Math.min(a.filters.limit, MAX_ROWS)) : a.records } };
    }
    case "ui.notice":
      return { ...s, notice: { level: String(p.level ?? "info"), text: String(p.text ?? "").slice(0, 300), id: ++seq } };
    case "kill.triggered":
      return { ...s, agent: "killed", approvals: [] };
    default:
      return s;
  }
}
