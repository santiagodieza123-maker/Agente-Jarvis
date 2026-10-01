const KEY = "jarvis.compact";
export const SIZES = { full: [1100, 700], compact: [300, 380] } as const;

export function readCompact(storage: Pick<Storage, "getItem"> | null = safeStorage()): boolean {
  try { return storage?.getItem(KEY) === "1"; } catch { return false; }
}
export function saveCompact(v: boolean, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try { storage?.setItem(KEY, v ? "1" : "0"); } catch { /* sin almacenamiento: el modo no se recuerda */ }
}
function safeStorage(): Storage | null {
  try { return typeof localStorage === "undefined" ? null : localStorage; } catch { return null; }
}
