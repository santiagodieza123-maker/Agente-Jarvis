// Contrato HUD<->core: debe coincidir con ../schemas/events.schema.json
export const EVENT_TYPES = [
  "plan.updated", "action.started", "action.finished", "perception.frame",
  "approval.requested", "approval.granted", "approval.denied",
  "memory.changed", "permissions.changed", "ui.notice", "state.changed", "kill.triggered",
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
  | { type: "permissions.remove_root"; path: string };

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
