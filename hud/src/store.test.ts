import { describe, expect, it } from "vitest";
import { parseEvent, type JarvisEvent } from "./events";
import { initial, reduce } from "./store";

const ev = (type: JarvisEvent["type"], payload: Record<string, unknown> = {}): JarvisEvent => ({ v: "0.1.0", ts: 1, type, payload });
const apply = (...evs: JarvisEvent[]) => evs.reduce((s, e) => reduce(s, { kind: "event", event: e }), initial);

describe("store", () => {
  it("sigue el ciclo de una acción", () => {
    const s = apply(ev("action.started", { tool: "fs.read" }), ev("action.finished", { tool: "fs.read", ok: true }));
    expect(s.timeline).toHaveLength(1);
    expect(s.timeline[0].status).toBe("ok");
    expect(s.agent).toBe("thinking");
  });
  it("marca fallo y denegación", () => {
    const s = apply(ev("action.started", { tool: "x" }), ev("action.finished", { tool: "x", ok: false }),
      ev("approval.requested", { tool: "rm" }), ev("approval.denied", { tool: "rm" }));
    expect(s.timeline.map((t) => t.status)).toEqual(["failed", "denied"]);
    expect(s.approvals).toHaveLength(0);
  });
  it("entra en 'awaiting' con aprobaciones pendientes", () => {
    expect(apply(ev("approval.requested", { tool: "rm", id: "a1" })).agent).toBe("awaiting");
  });
  it("kill.triggered es terminal incluso si luego se cierra la conexión", () => {
    const s = reduce(apply(ev("kill.triggered")), { kind: "conn", conn: "closed" });
    expect(s.agent).toBe("killed");
  });
  it("la desconexión sin kill es error", () => {
    expect(reduce(initial, { kind: "conn", conn: "closed" }).agent).toBe("error");
  });
  it("resuelve aprobaciones por id, no por nombre de herramienta", () => {
    const s = apply(ev("approval.requested", { tool: "rm", id: "a" }), ev("approval.requested", { tool: "rm", id: "b" }),
      ev("approval.granted", { tool: "rm", id: "a" }));
    expect(s.approvals.map((x) => x.id)).toEqual(["b"]);
    expect(s.agent).toBe("awaiting");
  });
  it("al reconectar sale de error", () => {
    const s = reduce(reduce(initial, { kind: "conn", conn: "closed" }), { kind: "conn", conn: "open" });
    expect(s.agent).toBe("idle");
  });
  it("limita la línea de tiempo", () => {
    const s = apply(...Array.from({ length: 300 }, () => ev("action.started", { tool: "t" })));
    expect(s.timeline).toHaveLength(200);
  });
  it("parseEvent rechaza basura y tipos desconocidos", () => {
    expect(parseEvent("no json")).toBeNull();
    expect(parseEvent(JSON.stringify({ ts: 1, type: "evil", payload: {} }))).toBeNull();
    expect(parseEvent(JSON.stringify(ev("state.changed")))).not.toBeNull();
  });
});

describe("memoria y permisos", () => {
  const mem = { notes: [{ id: 1, kind: "dato", content: "x", updated: 1 }], episodes: [], kinds: ["dato"], limits: { content: 1000, notes: 200 } };
  const perms = { classes: [{ name: "read", confirm: false, locked: false }], tools: [], roots: ["/a"] };
  it("guarda instantáneas válidas", () => {
    const s = apply(ev("memory.changed", mem), ev("permissions.changed", perms));
    expect(s.memory?.notes[0].content).toBe("x");
    expect(s.permissions?.roots).toEqual(["/a"]);
  });
  it("ignora instantáneas con forma inválida y conserva la anterior", () => {
    const s = apply(ev("memory.changed", mem), ev("memory.changed", { notes: "no" }), ev("permissions.changed", { classes: 1 }));
    expect(s.memory?.notes).toHaveLength(1);
    expect(s.permissions).toBeNull();
  });
  it("el aviso se puede descartar solo por su id", () => {
    const s = apply(ev("ui.notice", { level: "error", text: "mal" }));
    expect(s.notice?.text).toBe("mal");
    expect(reduce(s, { kind: "clear_notice", id: -1 }).notice).not.toBeNull();
    expect(reduce(s, { kind: "clear_notice", id: s.notice!.id }).notice).toBeNull();
  });
  it("recorta avisos largos", () => {
    expect(apply(ev("ui.notice", { text: "x".repeat(1000) })).notice!.text).toHaveLength(300);
  });
});
