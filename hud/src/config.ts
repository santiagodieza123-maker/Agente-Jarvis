import type { ConfigSnapshot } from "./events";

export const ACCENT_COLOR: Record<string, string> = { cian: "#2fb8ff", ámbar: "#ffc247", verde: "#35e08a", magenta: "#ff4fd8" };
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
