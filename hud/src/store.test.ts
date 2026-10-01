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

describe("auditoría en el store", () => {
  const snap = (records: unknown[], extra = {}) => ({ records, matched: records.length, total: records.length, event_types: ["a.b"], head: "H0",
    truncated: false, filters: { event: "", text: "", limit: 3 }, ...extra });
  const r = (seq: number, event = "a.b", data = {}) => ({ seq, ts: 1, event, data, prev: "p", hash: `h${seq}` });
  it("ignora registros en vivo hasta que el panel haya cargado", () => {
    expect(apply(ev("audit.appended", r(1))).audit).toBeNull();
  });
  it("antepone registros en vivo, respeta el límite, actualiza total/cabecera y no duplica", () => {
    let s = apply(ev("audit.changed", snap([r(2), r(1)])));
    s = [r(3), r(4), r(3)].reduce((acc, x) => reduce(acc, { kind: "event", event: ev("audit.appended", x) }), s);
    expect(s.audit!.records.map((x) => x.seq)).toEqual([4, 3, 2]);         // límite 3
    expect(s.audit!.total).toBe(4);
    expect(s.audit!.head).toBe("h4");
  });
  it("un registro que no cumple el filtro cuenta en el total pero no se muestra", () => {
    const s = apply(ev("audit.changed", snap([r(1)], { filters: { event: "a.b", text: "", limit: 10 } })),
      ev("audit.appended", r(2, "otro.evento")));
    expect(s.audit!.records).toHaveLength(1);
    expect(s.audit!.total).toBe(2);
    expect(s.audit!.event_types).toContain("otro.evento");                 // el selector se entera del tipo nuevo
  });
  it("guarda el resultado de la verificación y descarta formas inválidas", () => {
    let s = apply(ev("audit.verified", { ok: false, count: 2, bad_line: 3, head: "x" }));
    expect(s.auditVerified?.bad_line).toBe(3);
    s = reduce(s, { kind: "event", event: ev("audit.verified", { ok: "no" }) });
    expect(s.auditVerified?.bad_line).toBe(3);
  });
});

describe("avisos de aprobación", () => {
  it("conserva los avisos sensibles y descarta formas inválidas", () => {
    const s = apply(ev("approval.requested", { id: "a", tool: "shell.exec", args: {}, origin: "user", warnings: ["secretos"] }),
                    ev("approval.requested", { id: "b", tool: "x", args: {}, origin: "user", warnings: "no-es-lista" }));
    expect(s.approvals[0].warnings).toEqual(["secretos"]);
    expect(s.approvals[1].warnings).toEqual([]);
  });
});

describe("perception.frame", () => {
  const frame = { image: "QUJD", width: 100, height: 50, title: "Notas", process: "n.exe", seq: 2, highlight: 3, action: "clic en 3",
    elements: [{ id: 3, name: "OK", role: "button", interactive: true, enabled: true, rect: [1, 2, 30, 20] }, { id: 4, name: "x", role: "text", interactive: false, enabled: true, rect: [0, 0, 1, 1] }, { id: "mal" }] };
  it("guarda el marco válido y descarta elementos malformados", () => {
    const s = apply(ev("perception.frame", frame));
    expect(s.frame?.title).toBe("Notas"); expect(s.frame?.elements).toHaveLength(2); expect(s.frame?.highlight).toBe(3);
  });
  it("ignora marcos inválidos (imagen no base64, dimensiones, enormes) y conserva el anterior", () => {
    const ok = apply(ev("perception.frame", frame));
    for (const bad of [{ ...frame, image: "<script>" }, { ...frame, width: 0 }, { ...frame, image: "A".repeat(3_000_001) }, { ...frame, elements: "x" }, { ...frame, title: 5 }]) {
      expect(reduce(ok, { kind: "event", event: ev("perception.frame", bad) }).frame).toBe(ok.frame);
    }
  });
  it("el pánico borra la captura", () => {
    expect(apply(ev("perception.frame", frame), ev("kill.triggered")).frame).toBeNull();
  });
});

describe("system.stats", () => {
  const stat = (n: number) => ({ ts: n, uptime: 10, threads: 4, loop_lag_ms: 1.5, clients: 1, cpu: { process: n, system: 20, cores: 8 }, memory: { rss: 1e8, system_percent: 40, system_total: 1e10 },
    gpu: null, children: [{ pid: 5, name: "x", cpu: 1, rss: 1 }, { pid: "mal" }], llm: { calls: 2, errors: 0, last_ms: 300, avg_ms: 250, p95_ms: 400, ready: true, model: "m" },
    components: [{ name: "núcleo", state: "ok", detail: "" }, { nombre: 1 }] });
  it("acumula muestras (máx. 60) y filtra elementos malformados", () => {
    const s = apply(...Array.from({ length: 75 }, (_, i) => ev("system.stats", stat(i))));
    expect(s.stats).toHaveLength(60); expect(s.stats[59].cpu.process).toBe(74);
    expect(s.stats[0].children).toHaveLength(1); expect(s.stats[0].components).toHaveLength(1);
  });
  it("ignora muestras inválidas", () => {
    const s = apply(ev("system.stats", stat(1)), ev("system.stats", { ...stat(2), cpu: "x" }), ev("system.stats", { ...stat(3), llm: { calls: "no" } }), ev("system.stats", {}));
    expect(s.stats).toHaveLength(1);
  });
  it("acepta GPU y latencias nulas", () => {
    const s = apply(ev("system.stats", { ...stat(1), gpu: { name: "RTX", util: 5, mem_used: 1, mem_total: 2 }, llm: { calls: 0, errors: 0, last_ms: null, avg_ms: null, p95_ms: null, ready: false, model: null } }));
    expect(s.stats[0].gpu?.name).toBe("RTX"); expect(s.stats[0].llm.last_ms).toBeNull();
  });
});

describe("broker.changed", () => {
  it("acepta el estado del broker y normaliza campos", () => {
    const s = apply(ev("broker.changed", { available: true, running: true, elevated: true, pid: 12, dry_run: false, services: ["Spooler", 5, "W32Time"], error: "" }));
    expect(s.broker).toEqual({ available: true, running: true, elevated: true, pid: 12, dry_run: false, services: ["Spooler", "W32Time"], error: "" });
    expect(apply(ev("broker.changed", { available: false, running: false })).broker?.available).toBe(false);
  });
  it("ignora estados inválidos y conserva el anterior", () => {
    const ok = apply(ev("broker.changed", { available: true, running: false }));
    expect(reduce(ok, { kind: "event", event: ev("broker.changed", { available: "si" }) }).broker).toBe(ok.broker);
  });
});
