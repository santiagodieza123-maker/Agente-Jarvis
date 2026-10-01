import { describe, expect, it } from "vitest";
import { ACCENT_COLOR, THEMES, applyTheme, themeOf } from "./themes";

describe("temas", () => {
  it("cada tema define colores válidos y tiene etiqueta", () => {
    for (const [k, t] of Object.entries(THEMES)) {
      for (const c of [t.c, t.idle, t.thinking, t.bg0, t.bg1]) expect(c, k).toMatch(/^#[0-9a-f]{6}$/i);
      expect(t.label.length).toBeGreaterThan(0);
    }
    expect(Object.keys(THEMES)).toEqual(["cian", "ámbar", "verde", "magenta", "rojo", "hielo"]);          // los mismos que valida el núcleo
    expect(ACCENT_COLOR.rojo).toBe(THEMES.rojo.c);
  });
  it("un tema desconocido cae al de Jarvis", () => { expect(themeOf("nope")).toBe(THEMES.cian); expect(themeOf(undefined)).toBe(THEMES.cian); });
  it("aplica variables CSS", () => {
    const set: Record<string, string> = {};
    applyTheme("verde", { style: { setProperty: (k: string, v: string) => { set[k] = v; } } } as unknown as HTMLElement);
    expect(set).toEqual({ "--c": THEMES.verde.c, "--bg0": THEMES.verde.bg0, "--bg1": THEMES.verde.bg1 });
  });
});
