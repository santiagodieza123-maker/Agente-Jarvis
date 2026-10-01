export const TARGET_RATE = 16000;

export function rms(x: Float32Array): number {
  if (!x.length) return 0;
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return Math.sqrt(s / x.length);
}

/** Reduce la frecuencia de muestreo promediando (suficiente para voz). */
export function downsample(input: Float32Array, inRate: number, outRate = TARGET_RATE): Float32Array {
  if (outRate >= inRate) return input;
  const ratio = inRate / outRate, n = Math.floor(input.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), b = Math.min(input.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = a; j < b; j++) s += input[j];
    out[i] = s / Math.max(1, b - a);
  }
  return out;
}

export function concat(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

/** WAV PCM de 16 bits, mono. */
export function encodeWav(samples: Float32Array, sampleRate = TARGET_RATE): Uint8Array {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

export function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export interface SegOpts { sampleRate: number; threshold?: number; startMs?: number; endSilenceMs?: number; minMs?: number; maxMs?: number; preRollMs?: number }

/** Detector de frases por energía: devuelve la frase completa cuando hay voz seguida de un silencio. */
export class Segmenter {
  level = 0;
  private o: Required<SegOpts>;
  private pre: Float32Array[] = []; private preLen = 0;
  private buf: Float32Array[] = []; private bufLen = 0;
  private speaking = false; private loud = 0; private quiet = 0; private voiced = 0;   // voiced: ms de voz (sin contar el silencio)
  constructor(o: SegOpts) {
    this.o = { threshold: 0.02, startMs: 120, endSilenceMs: 900, minMs: 250, maxMs: 25000, preRollMs: 250, ...o };
  }
  private ms(n: number) { return (n / this.o.sampleRate) * 1000; }
  get active() { return this.speaking; }
  push(chunk: Float32Array): Float32Array | null {
    const e = rms(chunk), isLoud = e >= this.o.threshold, dur = this.ms(chunk.length);
    this.level = this.level * 0.6 + Math.min(1, e * 8) * 0.4;
    if (!this.speaking) {
      this.pre.push(chunk); this.preLen += chunk.length;
      while (this.pre.length > 1 && this.ms(this.preLen - this.pre[0].length) >= this.o.preRollMs) this.preLen -= this.pre.shift()!.length;
      this.loud = isLoud ? this.loud + dur : 0;
      if (this.loud >= this.o.startMs) { this.speaking = true; this.buf = [...this.pre]; this.bufLen = this.preLen; this.pre = []; this.preLen = 0; this.quiet = 0; this.voiced = this.loud; }
      return null;
    }
    this.buf.push(chunk); this.bufLen += chunk.length;
    this.quiet = isLoud ? 0 : this.quiet + dur;
    if (isLoud) this.voiced += dur;
    if (this.quiet >= this.o.endSilenceMs || this.ms(this.bufLen) >= this.o.maxMs) return this.finish();
    return null;
  }
  /** Cierra la frase en curso (p. ej. al parar el micrófono). */
  flush(): Float32Array | null { return this.speaking ? this.finish() : null; }
  private finish(): Float32Array | null {
    const out = this.voiced >= this.o.minMs ? concat(this.buf) : null;                       // minMs cuenta solo voz, no silencio
    this.speaking = false; this.buf = []; this.bufLen = 0; this.quiet = 0; this.loud = 0; this.voiced = 0;
    return out;
  }
}
