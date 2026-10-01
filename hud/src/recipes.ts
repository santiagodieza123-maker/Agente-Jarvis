import type { Precondition, Recipe } from "./events";

const PARAM = /\{\{([a-z][a-z0-9_]{0,19})\}\}/g;

/** Parámetros ({{nombre}}) que usa una receta, en orden de aparición y sin repetir. */
export function recipeParams(r: Pick<Recipe, "steps">): string[] {
  const out: string[] = [];
  const walk = (v: unknown) => {
    if (typeof v === "string") {
      for (const m of v.matchAll(PARAM)) if (!out.includes(m[1])) out.push(m[1]);
    } else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  r.steps.forEach((s) => walk(s.args));
  return out;
}

/** «ruta: /a/b» y «ventana: Notas» (una por línea) -> precondiciones. El núcleo vuelve a validar. */
export function parsePre(text: string): { ok: true; items: Precondition[] } | { ok: false; error: string } {
  const items: Precondition[] = [];
  for (const [i, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim();
    if (!line) continue;
    const m = /^(ruta|ventana)\s*:\s*(.+)$/i.exec(line);
    if (!m) return { ok: false, error: `línea ${i + 1}: usa «ruta: …» o «ventana: …»` };
    items.push(m[1].toLowerCase() === "ruta" ? { type: "path_exists", path: m[2].trim() } : { type: "window_contains", text: m[2].trim() });
  }
  if (items.length > 10) return { ok: false, error: "máximo 10 precondiciones" };
  return { ok: true, items };
}

export const preToText = (items: Precondition[]) => items.map((p) => (p.type === "path_exists" ? `ruta: ${p.path}` : `ventana: ${p.text}`)).join("\n");
export const successRate = (r: Pick<Recipe, "runs" | "ok_runs">) => (r.runs ? `${Math.round((100 * r.ok_runs) / r.runs)} % (${r.ok_runs}/${r.runs})` : "sin ejecuciones");
