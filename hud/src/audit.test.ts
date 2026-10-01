import { describe, expect, it } from "vitest";
import { asAudit, asRecord, asVerified, brief, matches, severity, type AuditRecord } from "./audit";

const rec = (event: string, data: Record<string, unknown> = {}, seq = 1): AuditRecord => ({ seq, ts: 1, event, data, prev: "p", hash: "h" });

describe("audit", () => {
  it("matches replica el filtro del servidor", () => {
    const r = rec("action.denied", { tool: "fs.DELETE" });
    expect(matches(r, { event: "", text: "", limit: 10 })).toBe(true);
    expect(matches(r, { event: "action.denied", text: "", limit: 10 })).toBe(true);
    expect(matches(r, { event: "task.started", text: "", limit: 10 })).toBe(false);
    expect(matches(r, { event: "", text: "fs.delete", limit: 10 })).toBe(true);     // sin distinguir mayúsculas
    expect(matches(r, { event: "", text: "DENIED", limit: 10 })).toBe(true);          // también en el nombre del evento
    expect(matches(r, { event: "", text: "otra-cosa", limit: 10 })).toBe(false);
  });
  it("clasifica la severidad", () => {
    expect(severity("action.denied")).toBe("bad");
    expect(severity("kill.triggered")).toBe("bad");
    expect(severity("task.aborted")).toBe("bad");
    expect(severity("approval.resolved")).toBe("warn");
    expect(severity("permissions.set_confirm")).toBe("warn");
    expect(severity("task.started")).toBe("info");
    expect(severity("action.finished")).toBe("good");
    expect(severity("core.started")).toBe("neutral");
  });
  it("brief resume y recorta", () => {
    expect(brief(rec("x", { tool: "fs.read" }))).toBe("fs.read");
    expect(brief(rec("x", { a: 1 }))).toBe('{"a":1}');
    expect(brief(rec("x", { goal: "g".repeat(200) }))).toHaveLength(91);
  });
  it("validadores rechazan formas inválidas", () => {
    expect(asAudit({ records: 1 })).toBeNull();
    expect(asAudit({ records: [], event_types: [], filters: null, total: 0, head: "" })).toBeNull();
    expect(asAudit({ records: [], event_types: [], filters: {}, total: 0, head: "h" })).not.toBeNull();
    expect(asVerified({ ok: "si", count: 1 })).toBeNull();
    expect(asVerified({ ok: true, count: 3, bad_line: null, head: "h" })?.count).toBe(3);
    expect(asRecord({ seq: "1" })).toBeNull();
    expect(asRecord({ seq: 1, event: "e", hash: "h", data: null })).toBeNull();
    expect(asRecord({ seq: 1, event: "e", hash: "h", data: {} })).not.toBeNull();
  });
});
