import { describe, expect, it } from "vitest";
import { Segmenter, concat, downsample, encodeWav, rms, toBase64 } from "./audio";
import { matchWake } from "./wake";

const tone = (n: number, amp: number) => Float32Array.from({ length: n }, (_, i) => amp * Math.sin(i / 5));
const silence = (n: number) => new Float32Array(n);

describe("audio", () => {
  it("rms", () => {
    expect(rms(new Float32Array(0))).toBe(0);
    expect(rms(Float32Array.from([1, -1, 1, -1]))).toBeCloseTo(1);
    expect(rms(tone(1000, 0.5))).toBeCloseTo(0.5 / Math.SQRT2, 1);
  });
  it("downsample promedia y cambia la longitud", () => {
    const out = downsample(Float32Array.from([1, 1, 3, 3, 5, 5]), 48000, 16000);
    expect(out).toHaveLength(2); expect([...out].map((v) => Math.round(v * 10) / 10)).toEqual([1.7, 4.3]);
    const same = Float32Array.from([1, 2]);
    expect(downsample(same, 16000, 16000)).toBe(same);
  });
  it("encodeWav: cabecera RIFF/WAVE, 16 bits mono 16 kHz y saturación", () => {
    const w = encodeWav(Float32Array.from([0, 1, -1, 2, -2]), 16000), v = new DataView(w.buffer);
    const str = (o: number, n: number) => String.fromCharCode(...w.subarray(o, o + n));
    expect([str(0, 4), str(8, 4), str(12, 4), str(36, 4)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect(v.getUint32(4, true)).toBe(36 + 10); expect(v.getUint16(22, true)).toBe(1); expect(v.getUint32(24, true)).toBe(16000); expect(v.getUint16(34, true)).toBe(16);
    expect(v.getUint32(40, true)).toBe(10); expect(w.length).toBe(54);
    expect([0, 1, 2, 3, 4].map((i) => v.getInt16(44 + i * 2, true))).toEqual([0, 32767, -32768, 32767, -32768]);
  });
  it("base64 de buffers grandes", () => {
    const big = new Uint8Array(100_000).map((_, i) => i % 251);
    const b = toBase64(big), back = Uint8Array.from(atob(b), (c) => c.charCodeAt(0));
    expect(back).toHaveLength(100_000); expect(back[99_999]).toBe(big[99_999]);
  });
  it("concat", () => { expect([...concat([Float32Array.from([1]), Float32Array.from([2, 3])])]).toEqual([1, 2, 3]); });
});

describe("Segmenter", () => {
  const R = 16000, blk = (ms: number, amp: number) => (amp ? tone((R * ms) / 1000, amp) : silence((R * ms) / 1000));
  const run = (seg: Segmenter, parts: [number, number][]) => { const out: Float32Array[] = []; for (const [ms, a] of parts) for (let t = 0; t < ms; t += 50) { const r = seg.push(blk(50, a)); if (r) out.push(r); } return out; };
  it("detecta una frase tras el silencio, con pre-roll", () => {
    const seg = new Segmenter({ sampleRate: R });
    const out = run(seg, [[500, 0], [1200, 0.3], [1200, 0]]);
    expect(out).toHaveLength(1);
    const ms = (out[0].length / R) * 1000;
    expect(ms).toBeGreaterThan(1200); expect(ms).toBeLessThan(1200 + 900 + 400);         // voz + silencio de cierre + pre-roll
  });
  it("ignora ruido breve y silencio", () => {
    const seg = new Segmenter({ sampleRate: R });
    expect(run(seg, [[3000, 0], [50, 0.3], [2000, 0]])).toHaveLength(0);               // un chasquido de 50 ms no es voz
    expect(seg.active).toBe(false);
  });
  it("descarta frases demasiado cortas y separa varias", () => {
    const seg = new Segmenter({ sampleRate: R, minMs: 700 });
    expect(run(seg, [[200, 0.3], [1200, 0]])).toHaveLength(0);
    const out = run(new Segmenter({ sampleRate: R }), [[800, 0.3], [1100, 0], [800, 0.3], [1100, 0]]);
    expect(out).toHaveLength(2);
  });
  it("corta las frases larguísimas y permite flush", () => {
    const seg = new Segmenter({ sampleRate: R, maxMs: 2000 });
    expect(run(seg, [[2600, 0.3]]).length).toBeGreaterThanOrEqual(1);
    const s2 = new Segmenter({ sampleRate: R });
    run(s2, [[1000, 0.3]]);
    expect(s2.active).toBe(true); expect(s2.flush()!.length).toBeGreaterThan(R * 0.9); expect(s2.flush()).toBeNull();
  });
  it("el nivel sube con la voz", () => {
    const seg = new Segmenter({ sampleRate: R }); run(seg, [[300, 0.4]]); const hi = seg.level; run(seg, [[600, 0]]);
    expect(hi).toBeGreaterThan(0.3); expect(seg.level).toBeLessThan(hi);
  });
});

describe("palabra de activación", () => {
  it("reconoce variantes y devuelve la orden con sus tildes", () => {
    expect(matchWake("Jarvis, crea un archivo")).toEqual({ matched: true, rest: "crea un archivo" });
    expect(matchWake("  oye Jarvis: ¿qué hora es?")).toEqual({ matched: true, rest: "¿qué hora es?" });
    expect(matchWake("Hey jarvis abre la calculadora")).toEqual({ matched: true, rest: "abre la calculadora" });
    expect(matchWake("YARVIS. Léeme el archivo")).toEqual({ matched: true, rest: "Léeme el archivo" });
    expect(matchWake("jarvis")).toEqual({ matched: true, rest: "" });
  });
  it("no se activa con otras frases", () => {
    for (const t of ["", "crea un archivo", "dile a Jarvis que venga", "jarvisito hola", "ok google", "esto no es jarvis"]) expect(matchWake(t).matched, t).toBe(false);
  });
});
