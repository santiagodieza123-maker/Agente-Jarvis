// Contrato HUD<->core: debe coincidir con ../schemas/events.schema.json
export const EVENT_TYPES = [
  "plan.updated", "action.started", "action.finished", "perception.frame",
  "approval.requested", "approval.granted", "approval.denied",
  "memory.changed", "permissions.changed", "config.changed", "extensions.changed", "system.stats", "voice.transcript", "broker.changed", "audit.changed", "audit.appended", "audit.verified", "ui.notice", "state.changed", "kill.triggered",
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
  | { type: "recipes.save"; episode_id: number; name: string }
  | { type: "recipes.delete"; id: number }
  | { type: "recipes.param"; id: number; step: number; arg: string; name: string }
  | { type: "recipes.set_preconditions"; id: number; items: Precondition[] }
  | { type: "recipes.run"; id: number; params?: Record<string, string> }
  | { type: "voice.transcribe"; id: string; mime: string; audio: string }
  | { type: "broker.status" }
  | { type: "broker.start" }
  | { type: "broker.stop" }
  | { type: "broker.allow_service"; name: string }
  | { type: "audit.get"; limit?: number; event?: string; text?: string }
  | { type: "audit.export"; event?: string; text?: string }
  | { type: "audit.verify" };

export interface Note { id: number; kind: string; content: string; updated: number }
export interface Episode { id: number; ts: number; goal: string; status: string; steps: number; answer: string; saveable?: boolean }
export type Precondition = { type: "path_exists"; path: string } | { type: "window_contains"; text: string };
export interface RecipeStep { tool: string; args: Record<string, unknown> }
export interface Recipe { id: number; name: string; goal: string; steps: RecipeStep[]; params: Record<string, string>; pre: Precondition[]; tainted: boolean; runs: number; ok_runs: number; last_run: number | null; last_error: string }
export interface MemorySnapshot { notes: Note[]; episodes: Episode[]; kinds: string[]; recipes?: Recipe[]; limits: { content: number; notes: number } }
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

export interface FrameElement { id: number; name: string; role: string; interactive: boolean; enabled: boolean; rect: [number, number, number, number] }
export interface Frame { image: string; width: number; height: number; title: string; process: string; seq: number; elements: FrameElement[]; highlight: number | null; action: string }
const MAX_FRAME_B64 = 3_000_000;
export function asFrame(p: Record<string, unknown>): Frame | null {
  if (typeof p.image !== "string" || p.image.length === 0 || p.image.length > MAX_FRAME_B64 || !/^[A-Za-z0-9+/=]+$/.test(p.image)) return null;
  if (!Number.isFinite(p.width) || !Number.isFinite(p.height) || (p.width as number) <= 0 || (p.height as number) <= 0) return null;
  if (!isArr(p.elements) || typeof p.title !== "string" || typeof p.action !== "string") return null;
  const els = (p.elements as Record<string, unknown>[]).filter((e) => !!e && typeof e.id === "number" && typeof e.role === "string" && typeof e.name === "string"
    && typeof e.interactive === "boolean" && isArr(e.rect) && (e.rect as unknown[]).length === 4 && (e.rect as unknown[]).every((n) => Number.isFinite(n)));
  return { image: p.image, width: p.width as number, height: p.height as number, title: p.title, process: String(p.process ?? ""), seq: Number(p.seq ?? 0),
    elements: els.slice(0, 300) as unknown as FrameElement[], highlight: typeof p.highlight === "number" ? p.highlight : null, action: p.action };
}

export interface Stats {
  ts: number; uptime: number; threads: number; loop_lag_ms: number; clients: number;
  cpu: { process: number; system: number; cores: number };
  memory: { rss: number; system_percent: number; system_total: number };
  gpu: { name: string; util: number; mem_used: number; mem_total: number } | null;
  children: { pid: number; name: string; cpu: number; rss: number }[];
  llm: { calls: number; errors: number; last_ms: number | null; avg_ms: number | null; p95_ms: number | null; ready: boolean; model: string | null };
  components: { name: string; state: string; detail: string }[];
}
const num = (v: unknown) => typeof v === "number" && Number.isFinite(v);
export function asStats(p: Record<string, unknown>): Stats | null {
  const c = p.cpu as Record<string, unknown> | undefined, m = p.memory as Record<string, unknown> | undefined, l = p.llm as Record<string, unknown> | undefined;
  if (!num(p.ts) || !num(p.uptime) || !num(p.threads) || !num(p.loop_lag_ms) || !num(p.clients)) return null;
  if (!c || !num(c.process) || !num(c.system) || !num(c.cores) || !m || !num(m.rss) || !num(m.system_percent) || !num(m.system_total)) return null;
  if (!l || !num(l.calls) || !num(l.errors) || typeof l.ready !== "boolean" || !isArr(p.children) || !isArr(p.components)) return null;
  const g = p.gpu as Record<string, unknown> | null;
  const gpu = g && num(g.util) && num(g.mem_used) && num(g.mem_total) ? { name: String(g.name ?? ""), util: g.util as number, mem_used: g.mem_used as number, mem_total: g.mem_total as number } : null;
  const children = (p.children as Record<string, unknown>[]).filter((k) => num(k.pid) && num(k.cpu) && num(k.rss)).slice(0, 20).map((k) => ({ pid: k.pid as number, name: String(k.name ?? ""), cpu: k.cpu as number, rss: k.rss as number }));
  const components = (p.components as Record<string, unknown>[]).filter((k) => typeof k.name === "string" && typeof k.state === "string").slice(0, 40).map((k) => ({ name: String(k.name), state: String(k.state), detail: String(k.detail ?? "") }));
  const opt = (v: unknown) => (num(v) ? (v as number) : null);
  return { ts: p.ts as number, uptime: p.uptime as number, threads: p.threads as number, loop_lag_ms: p.loop_lag_ms as number, clients: p.clients as number,
    cpu: { process: c.process as number, system: c.system as number, cores: c.cores as number }, memory: { rss: m.rss as number, system_percent: m.system_percent as number, system_total: m.system_total as number },
    gpu, children, components, llm: { calls: l.calls as number, errors: l.errors as number, last_ms: opt(l.last_ms), avg_ms: opt(l.avg_ms), p95_ms: opt(l.p95_ms), ready: l.ready as boolean, model: typeof l.model === "string" ? l.model : null } };
}

export interface BrokerSnapshot { available: boolean; running: boolean; elevated?: boolean; pid?: number | null; dry_run?: boolean; services?: string[]; error?: string }
export function asBroker(p: Record<string, unknown>): BrokerSnapshot | null {
  if (typeof p.available !== "boolean" || typeof p.running !== "boolean") return null;
  return { available: p.available, running: p.running, elevated: p.elevated === true, pid: typeof p.pid === "number" ? p.pid : null, dry_run: p.dry_run === true,
    services: isArr(p.services) ? (p.services as unknown[]).filter((x): x is string => typeof x === "string").slice(0, 50) : [], error: typeof p.error === "string" ? p.error.slice(0, 200) : "" };
}
