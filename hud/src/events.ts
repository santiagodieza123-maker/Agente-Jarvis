// Contrato HUD<->core: debe coincidir con ../schemas/events.schema.json
export const EVENT_TYPES = [
  "plan.updated", "action.started", "action.finished", "perception.frame",
  "approval.requested", "approval.granted", "approval.denied",
  "memory.changed", "state.changed", "kill.triggered",
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
  | { type: "panic" };
