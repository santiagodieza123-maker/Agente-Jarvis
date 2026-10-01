import { describe, expect, it } from "vitest";
import { parsePre, preToText, recipeParams, successRate } from "./recipes";

describe("recetas (cliente)", () => {
  it("encuentra parámetros anidados sin repetir", () => {
    const r = { steps: [{ tool: "a", args: { p: "/x/{{ruta}}", c: "Hola {{n}} {{n}}", l: ["{{otro}}"], o: { k: "{{n}}" }, num: 3 } }, { tool: "b", args: { q: "{{ruta}}" } }] };
    expect(recipeParams(r)).toEqual(["ruta", "n", "otro"]);
    expect(recipeParams({ steps: [] })).toEqual([]);
    expect(recipeParams({ steps: [{ tool: "a", args: { x: "{{Mal}} {{1x}} {x}" } }] })).toEqual([]);
  });
  it("parsea y serializa precondiciones", () => {
    const r = parsePre("ruta: C:\\datos\\in.csv\n\nVentana : Bloc de notas");
    expect(r).toEqual({ ok: true, items: [{ type: "path_exists", path: "C:\\datos\\in.csv" }, { type: "window_contains", text: "Bloc de notas" }] });
    expect(preToText(r.ok ? r.items : [])).toBe("ruta: C:\\datos\\in.csv\nventana: Bloc de notas");
    for (const bad of ["otra: x", "ruta:", "sin formato"]) expect(parsePre(bad).ok).toBe(false);
    expect(parsePre(Array.from({ length: 11 }, (_, i) => `ruta: /${i}`).join("\n")).ok).toBe(false);
  });
  it("tasa de éxito", () => {
    expect(successRate({ runs: 0, ok_runs: 0 })).toBe("sin ejecuciones");
    expect(successRate({ runs: 4, ok_runs: 3 })).toBe("75 % (3/4)");
  });
});
