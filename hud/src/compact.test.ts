import { describe, expect, it } from "vitest";
import { SIZES, readCompact, saveCompact } from "./compact";

const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };
describe("modo compacto", () => {
  it("se recuerda", () => {
    const s = mem();
    expect(readCompact(s)).toBe(false);
    saveCompact(true, s); expect(readCompact(s)).toBe(true);
    saveCompact(false, s); expect(readCompact(s)).toBe(false);
  });
  it("sobrevive a un almacenamiento que lanza o no existe", () => {
    const bad = { getItem: () => { throw new Error("x"); }, setItem: () => { throw new Error("x"); } };
    expect(readCompact(bad)).toBe(false);
    expect(() => saveCompact(true, bad)).not.toThrow();
    expect(readCompact(null)).toBe(false);
    expect(() => saveCompact(true, null)).not.toThrow();
  });
  it("tamaños razonables", () => { expect(SIZES.compact[0]).toBeLessThan(SIZES.full[0]); });
});
