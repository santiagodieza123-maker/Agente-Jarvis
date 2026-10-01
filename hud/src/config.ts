import type { ConfigSnapshot } from "./events";

export { ACCENT_COLOR } from "./themes";
export const LIMIT_FIELDS = ["max_steps", "max_failures", "approval_timeout", "token_budget"] as const;
export type LimitField = (typeof LIMIT_FIELDS)[number];

/** Convierte los borradores de texto en enteros dentro de los rangos del núcleo; el núcleo vuelve a validar. */
export function parseLimits(draft: Record<LimitField, string>, spec: ConfigSnapshot["spec"]):
  { ok: true; values: Record<LimitField, number> } | { ok: false; error: string } {
  const out = {} as Record<LimitField, number>;
  for (const f of LIMIT_FIELDS) {
    const raw = draft[f].trim();
    if (!/^\d+$/.test(raw)) return { ok: false, error: `${f}: entero ≥ 0` };
    const n = Number(raw), { min, max } = spec[f] ?? { min: null, max: null };
    if ((min !== null && n < min) || (max !== null && n > max)) return { ok: false, error: `${f}: entre ${min} y ${max}` };
    out[f] = n;
  }
  return { ok: true, values: out };
}

export function changed<T extends Record<string, unknown>>(next: T, cur: Record<string, unknown>): Partial<T> {
  return Object.fromEntries(Object.entries(next).filter(([k, v]) => cur[k] !== v)) as Partial<T>;
}

const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
/** Texto «NOMBRE=valor» (una por línea; # comenta) -> variables. El núcleo vuelve a validar. */
export function parseEnvLines(text: string): { ok: true; env: Record<string, string> } | { ok: false; error: string } {
  const env: Record<string, string> = {};
  for (const [i, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    const k = eq < 0 ? "" : line.slice(0, eq).trim(), v = eq < 0 ? "" : line.slice(eq + 1).trim();
    if (!ENV_NAME.test(k) || !v) return { ok: false, error: `línea ${i + 1}: usa NOMBRE=valor` };
    if (k in env) return { ok: false, error: `línea ${i + 1}: ${k} repetida` };
    env[k] = v;
  }
  if (Object.keys(env).length > 16) return { ok: false, error: "máximo 16 variables" };
  return { ok: true, env };
}
