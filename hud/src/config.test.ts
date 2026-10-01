import { describe, expect, it } from "vitest";
import { changed, parseLimits } from "./config";
import { asConfig } from "./events";
import { initial, reduce } from "./store";

const spec = { max_steps: { min: 1, max: 50, restart: false }, max_failures: { min: 1, max: 10, restart: false },
  approval_timeout: { min: 10, max: 600, restart: false }, token_budget: { min: 0, max: 5000000, restart: false } };
const d = { max_steps: "15", max_failures: "3", approval_timeout: "120", token_budget: "0" };
const snap = {
  values: { model: "m", max_steps: 15, max_failures: 3, approval_timeout: 120, token_budget: 0, browser_headed: false, accent: "cian" },
  spec, accents: ["cian"], restart: ["browser_headed"], api_key: { configured: true, source: "almacén", hint: "…abcd", backend: "archivo" },
  usage: { calls: 1, input: 2, output: 3 }, llm_ready: true, fixed: { kill_hotkey: "Ctrl+Shift+F10" },
};

describe("parseLimits", () => {
  it("acepta valores válidos", () => {
    expect(parseLimits(d, spec)).toEqual({ ok: true, values: { max_steps: 15, max_failures: 3, approval_timeout: 120, token_budget: 0 } });
  });
  it("rechaza vacíos, decimales, negativos, texto y fuera de rango", () => {
    for (const bad of ["", " ", "1.5", "-1", "abc", "1e3", "0x10", "51", "0"]) expect(parseLimits({ ...d, max_steps: bad }, spec).ok).toBe(false);
    expect(parseLimits({ ...d, token_budget: "5000001" }, spec).ok).toBe(false);
    expect(parseLimits({ ...d, approval_timeout: "9" }, spec).ok).toBe(false);
    expect(parseLimits({ ...d, token_budget: "0" }, spec).ok).toBe(true);   // 0 = sin límite
  });
});

describe("changed", () => {
  it("devuelve solo lo que difiere", () => {
    expect(changed({ a: 1, b: 2 }, { a: 1, b: 3 })).toEqual({ b: 2 });
    expect(changed({ a: 1 }, { a: 1 })).toEqual({});
  });
});

describe("asConfig / store", () => {
  it("valida la forma de la instantánea", () => {
    expect(asConfig(snap as never)).not.toBeNull();
    expect(asConfig({ ...snap, usage: { calls: "x" } } as never)).toBeNull();
    expect(asConfig({ ...snap, values: { ...snap.values, max_steps: "15" } } as never)).toBeNull();
    expect(asConfig({} as never)).toBeNull();
  });
  it("guarda la configuración válida y conserva la anterior ante basura", () => {
    const ev = (payload: Record<string, unknown>) => ({ v: "0.1.0", ts: 1, type: "config.changed" as const, payload });
    const s1 = reduce(initial, { kind: "event", event: ev(snap) });
    expect(s1.config?.values.model).toBe("m");
    expect(reduce(s1, { kind: "event", event: ev({ values: 1 }) }).config).toBe(s1.config);
  });
});
