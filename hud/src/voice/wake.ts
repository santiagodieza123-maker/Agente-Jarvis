const strip = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "");
// «Jarvis» tal como lo transcribe un reconocedor en español/inglés
const WAKE = /^\s*(?:(?:hey|ey|oye|hola|ok|okay|vale)[\s,]+)?(?:jarvis|yarvis|jarbis|jarvi|yarbis|harvis|jarvez)\b[\s,.:;!?-]*/i;

/** Recorta del texto original los primeros `n` caracteres de su versión sin acentos (así la orden conserva sus tildes). */
function cutPrefix(text: string, n: number): string {
  let used = 0, i = 0;
  for (const ch of text) {
    if (used >= n) break;
    used += strip(ch).length;
    i += ch.length;
  }
  return text.slice(i);
}

/** ¿Empieza la frase por la palabra de activación? Devuelve la orden que sigue (con sus acentos). */
export function matchWake(text: string): { matched: boolean; rest: string } {
  const m = WAKE.exec(strip(text));
  return m ? { matched: true, rest: cutPrefix(text, m[0].length).trim() } : { matched: false, rest: "" };
}
