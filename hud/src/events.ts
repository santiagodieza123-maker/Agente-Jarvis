// Contrato HUD<->core: debe coincidir con ../schemas/events.schema.json
export const EVENT_TYPES = [
  "plan.updated", "action.started", "action.finished", "perception.frame",
  "approval.requested", "approval.granted", "approval.denied",
  "memory.changed", "permissions.changed", "config.changed", "extensions.changed", "audit.changed", "audit.appended", "audit.verified", "ui.notice", "state.changed", "kill.triggered",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export interface JarvisEvent {
  v: string;
  ts: number;
  type: EventType;
  payload: Record<string, unknown>;
}

export function parseEvent(raw: string): JarvisEvent | null {
  try {
    const e = JSON.parse(raw);
    if (e && typeof e.ts === "number" && EVENT_TYPES.includes(e.type) && typeof e.payload === "object") return e;
  } catch { /* mensaje inválido: se ignora */ }
  return null;
}

// Mensajes HUD -> core
export type HudMessage =
  | { type: "task"; goal: string }
  | { type: "approval"; id: string; granted: boolean }
  | { type: "panic" }
  | { type: "memory.list" }
  | { type: "memory.add"; kind: string; content: string }
  | { type: "memory.update"; id: number; content: string }
  | { type: "memory.delete"; id: number }
  | { type: "memory.clear_episodes" }
  | { type: "permissions.get" }
  | { type: "permissions.set_confirm"; class: string; value: boolean }
  | { type: "permissions.set_tool"; tool: string; enabled: boolean }
  | { type: "permissions.add_root"; path: string }
  | { type: "permissions.remove_root"; path: string }
  | { type: "config.get" }
  | { type: "config.set"; values: Record<string, string | number | boolean> }
  | { type: "config.set_api_key"; key: string }
  | { type: "config.clear_api_key" }
  | { type: "config.test_llm" }
  | { type: "extensions.get" }
  | { type: "extensions.add"; name: string; command: string; confirmed: true; env?: Record<string, string> }
  | { type: "extensions.set_env"; name: string; env: Record<string, string> }
  | { type: "extensions.remove"; name: string }
  | { type: "extensions.set_enabled"; name: string; enabled: boolean }
  | { type: "extensions.restart"; name: string }
  | { type: "extensions.set_trust"; name: string; tool: string; read: boolean }
  | { type: "extensions.set_tool"; name: string; tool: string; enabled: boolean }
  | { type: "audit.get"; limit?: number; event?: string; text?: string }
  | { type: "audit.export"; event?: string; text?: string }
  | { type: "audit.verify" };

export interface Note { id: number; kind: string; content: string; updated: number }
export interface Episode { id: number; ts: number; goal: string; status: string; steps: number; answer: string }
export interface MemorySnapshot { notes: Note[]; episodes: Episode[]; kinds: string[]; limits: { content: number; notes: number } }
export interface PermClass { name: string; confirm: boolean; locked: boolean }
export interface PermTool { name: string; cls: string; enabled: boolean; description: string }
export interface PermissionsSnapshot { classes: PermClass[]; tools: PermTool[]; roots: string[] }

const isArr = Array.isArray;
export function asMemory(p: Record<string, unknown>): MemorySnapshot | null {
  return isArr(p.notes) && isArr(p.episodes) && isArr(p.kinds) && typeof p.limits === "object" ? (p as unknown as MemorySnapshot) : null;
}
export function asPermissions(p: Record<string, unknown>): PermissionsSnapshot | null {
  return isArr(p.classes) && isArr(p.tools) && isArr(p.roots) ? (p as unknown as PermissionsSnapshot) : null;
}

export interface ConfigValues {
  model: string; max_steps: number; max_failures: number; approval_timeout: number;
  token_budget: number; browser_headed: boolean; accent: string; confirm_with_extensions?: boolean;
}
export interface Bucket { calls: number; input: number; output: number }
export interface ConfigSnapshot {
  values: ConfigValues;
  spec: Record<string, { min: number | null; max: number | null; restart: boolean }>;
  accents: string[];
  restart: string[];
  api_key: { configured: boolean; source: string; hint: string; backend: string };
  usage: { calls: number; input: number; output: number; today?: Bucket; total?: Bucket };
  llm_ready: boolean;
  fixed: { kill_hotkey: string };
}
export function asConfig(p: Record<string, unknown>): ConfigSnapshot | null {
  const v = p.values as Record<string, unknown> | undefined, k = p.api_key as Record<string, unknown> | undefined;
  const u = p.usage as Record<string, unknown> | undefined, f = p.fixed as Record<string, unknown> | undefined;
  const ok = !!v && typeof v === "object" && typeof v.model === "string" && typeof v.accent === "string" && typeof v.browser_headed === "boolean"
    && ["max_steps", "max_failures", "approval_timeout", "token_budget"].every((n) => typeof v[n] === "number")
    && !!k && typeof k === "object" && typeof k.configured === "boolean" && typeof k.hint === "string" && typeof k.source === "string"
    && !!u && typeof u === "object" && ["calls", "input", "output"].every((n) => typeof u[n] === "number")
    && !!f && typeof f.kill_hotkey === "string" && !!p.spec && typeof p.spec === "object" && isArr(p.accents) && isArr(p.restart) && typeof p.llm_ready === "boolean";
  return ok ? (p as unknown as ConfigSnapshot) : null;
}

export interface ExtTool { name: string; raw: string; description: string; trusted: boolean; enabled: boolean }
export interface Extension { name: string; command: string; env_names?: string[]; enabled: boolean; state: "stopped" | "starting" | "running" | "error"; error: string; tools: ExtTool[]; log: string }
export interface ExtensionsSnapshot { extensions: Extension[]; limits: { extensions: number; tools: number } }
export function asExtensions(p: Record<string, unknown>): ExtensionsSnapshot | null {
  if (!isArr(p.extensions) || !p.limits || typeof p.limits !== "object") return null;
  const ok = (p.extensions as Record<string, unknown>[]).every((e) =>
    !!e && typeof e.name === "string" && typeof e.command === "string" && typeof e.enabled === "boolean" && typeof e.state === "string"
    && typeof e.error === "string" && typeof e.log === "string" && isArr(e.tools)
    && (e.tools as Record<string, unknown>[]).every((t) => !!t && typeof t.name === "string" && typeof t.raw === "string" && typeof t.trusted === "boolean" && typeof t.enabled === "boolean"));
  return ok ? (p as unknown as ExtensionsSnapshot) : null;
}
