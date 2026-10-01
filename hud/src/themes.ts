export interface Theme { c: string; idle: string; thinking: string; bg0: string; bg1: string; label: string }

// Cada tema define el color de acento del HUD y el degradado de fondo. Los estados (actuando, aprobación, error) mantienen sus colores.
export const THEMES: Record<string, Theme> = {
  cian: { label: "Jarvis", c: "#2fb8ff", idle: "#2fb8ff", thinking: "#7de7ff", bg0: "#06213a", bg1: "#020a14" },
  ámbar: { label: "Ámbar", c: "#ffc247", idle: "#ffb62e", thinking: "#ffe08a", bg0: "#2a1c06", bg1: "#0d0802" },
  verde: { label: "Matrix", c: "#35e08a", idle: "#2fd47f", thinking: "#9dffc8", bg0: "#062a1a", bg1: "#020d08" },
  magenta: { label: "Holograma", c: "#ff4fd8", idle: "#ff4fd8", thinking: "#ff9bec", bg0: "#2a0626", bg1: "#0d020c" },
  rojo: { label: "Mark VII", c: "#ff5a3c", idle: "#ff4a2e", thinking: "#ff9a7d", bg0: "#2e0a06", bg1: "#0d0302" },
  hielo: { label: "Hielo", c: "#bfe9ff", idle: "#a8dcff", thinking: "#e6f6ff", bg0: "#0d2438", bg1: "#04101a" },
};
export const themeOf = (name?: string | null): Theme => THEMES[name ?? ""] ?? THEMES.cian;
export const ACCENT_COLOR: Record<string, string> = Object.fromEntries(Object.entries(THEMES).map(([k, t]) => [k, t.c]));

export function applyTheme(name: string | undefined, root: HTMLElement = document.documentElement): Theme {
  const t = themeOf(name);
  root.style.setProperty("--c", t.c);
  root.style.setProperty("--bg0", t.bg0);
  root.style.setProperty("--bg1", t.bg1);
  return t;
}
