// Parámetros de conexión al núcleo. En Tauri los inyecta el shell (window.__JARVIS__);
// en desarrollo se pasan por la URL: ?port=8765&token=...
export interface Connection { port: number; token: string }

declare global { interface Window { __JARVIS__?: unknown } }

function valid(port: unknown, token: unknown): Connection | null {
  const p = typeof port === "string" && /^\d{1,5}$/.test(port) ? Number(port) : port;
  if (typeof p !== "number" || !Number.isInteger(p) || p < 1 || p > 65535) return null;
  if (typeof token !== "string" || token.length === 0) return null;
  return { port: p, token };
}

export function connection(win: { __JARVIS__?: unknown } = window, search: string = location.search): Connection | null {
  const inj = win.__JARVIS__;
  if (inj && typeof inj === "object") {
    const c = valid((inj as Record<string, unknown>).port, (inj as Record<string, unknown>).token);
    if (c) return c;
  }
  const q = new URLSearchParams(search);
  return valid(q.get("port"), q.get("token"));
}

export function endpoint(c: Connection | null = connection()): string | null {
  return c ? `ws://127.0.0.1:${c.port}/?token=${encodeURIComponent(c.token)}` : null;
}
