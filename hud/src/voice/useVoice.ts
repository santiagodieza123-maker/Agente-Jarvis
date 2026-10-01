import { useCallback, useEffect, useRef, useState } from "react";
import type { HudMessage } from "../events";
import { Segmenter, TARGET_RATE, concat, downsample, encodeWav, rms, toBase64 } from "./audio";
import { matchWake } from "./wake";

export interface Transcript { id: string; text?: string; silent?: boolean; error?: string; n: number }
export interface VoiceSettings { tts: boolean; voice: string; rate: number }
const KEY = "jarvis.voice";
const DEFAULTS: VoiceSettings = { tts: false, voice: "", rate: 1 };
const MIN_PTT = 0.3 * TARGET_RATE;      // menos de 0,3 s: se ignora
const MIN_GAP_MS = 1500;                // entre envíos en escucha continua: acota el gasto de API

export function loadVoiceSettings(): VoiceSettings {
  try {
    const d = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    return { tts: d.tts === true, voice: typeof d.voice === "string" ? d.voice.slice(0, 120) : "", rate: typeof d.rate === "number" && d.rate >= 0.5 && d.rate <= 2 ? d.rate : 1 };
  } catch { return DEFAULTS; }
}
const save = (s: VoiceSettings) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* sin almacenamiento */ } };

/** Texto apto para hablar: sin marcas de formato ni bloques de código, y acotado. */
export function speakable(text: string, max = 600): string {
  const t = text.replace(/```[\s\S]*?```/g, " (código) ").replace(/[`*_#>]/g, "").replace(/https?:\/\/\S+/g, " enlace ").replace(/\s+/g, " ").trim();
  return t.length > max ? t.slice(0, max).replace(/\s+\S*$/, "") + "…" : t;
}

interface Opts { send: (m: HudMessage) => void; onText: (text: string) => void; transcript: Transcript | null; lastAnswer: { text: string; key: number } | null }

export function useVoice({ send, onText, transcript, lastAnswer }: Opts) {
  const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== "undefined";
  const [ptt, setPtt] = useState(false), [wake, setWake] = useState(false), [busy, setBusy] = useState(false), [speaking, setSpeaking] = useState(false);
  const [level, setLevel] = useState(0), [error, setError] = useState("");
  const [settings, setSettingsState] = useState(loadVoiceSettings);
  const [voices, setVoices] = useState<string[]>([]);
  const r = useRef({ ctx: null as AudioContext | null, stream: null as MediaStream | null, node: null as AudioWorkletNode | null, seg: null as Segmenter | null,
    buf: [] as Float32Array[], ptt: false, wake: false, speaking: false, pending: new Map<string, "ptt" | "wake">(), n: 0, last: 0, lvl: 0 });
  const cb = useRef({ onText, send });
  cb.current = { onText, send };

  const closeMic = useCallback(() => {
    const s = r.current;
    s.node?.disconnect(); s.stream?.getTracks().forEach((t) => t.stop()); void s.ctx?.close();
    s.node = null; s.stream = null; s.ctx = null; s.seg = null; setLevel(0);
  }, []);
  const idle = useCallback(() => { if (!r.current.ptt && !r.current.wake) closeMic(); }, [closeMic]);

  const sendAudio = useCallback((samples: Float32Array, mode: "ptt" | "wake") => {
    const s = r.current, id = `${mode}-${++s.n}`;
    s.pending.set(id, mode); s.last = Date.now(); setBusy(true);
    cb.current.send({ type: "voice.transcribe", id, mime: "audio/wav", audio: toBase64(encodeWav(samples)) } as HudMessage);
  }, []);

  const onChunk = useCallback((raw: Float32Array) => {
    const s = r.current;
    if (!s.ctx || s.speaking) return;                                        // no escucharse a sí mismo mientras habla
    const ds = downsample(raw, s.ctx.sampleRate, TARGET_RATE);
    s.lvl = s.lvl * 0.7 + Math.min(1, rms(ds) * 8) * 0.3;
    setLevel(s.lvl);
    if (s.ptt) { s.buf.push(ds); return; }
    if (s.wake && s.seg) {
      const utt = s.seg.push(ds);
      if (utt && Date.now() - s.last >= MIN_GAP_MS) sendAudio(utt, "wake");
    }
  }, [sendAudio]);

  const openMic = useCallback(async () => {
    const s = r.current;
    if (s.ctx) return;
    if (!supported) throw new Error("este equipo no permite usar el micrófono");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    const ctx = new AudioContext();
    try { await ctx.audioWorklet.addModule("mic-worklet.js"); } catch (e) { stream.getTracks().forEach((t) => t.stop()); void ctx.close(); throw e; }
    const node = new AudioWorkletNode(ctx, "mic-capture");
    ctx.createMediaStreamSource(stream).connect(node);                       // sin conectar al destino: no hay realimentación
    node.port.onmessage = (e) => onChunk(e.data as Float32Array);
    s.ctx = ctx; s.stream = stream; s.node = node; s.seg = new Segmenter({ sampleRate: TARGET_RATE });
  }, [onChunk, supported]);

  const startPtt = useCallback(async () => {
    setError("");
    try { await openMic(); } catch (e) { setError(`Micrófono: ${(e as Error).message}`); return; }
    r.current.buf = []; r.current.ptt = true; setPtt(true);
  }, [openMic]);
  const stopPtt = useCallback(() => {
    const s = r.current;
    if (!s.ptt) return;
    s.ptt = false; setPtt(false);
    const samples = concat(s.buf); s.buf = [];
    if (samples.length >= MIN_PTT) sendAudio(samples, "ptt"); else setError("Muy corto: mantén pulsado mientras hablas");
    idle();
  }, [idle, sendAudio]);
  const togglePtt = useCallback(() => { if (r.current.ptt) stopPtt(); else void startPtt(); }, [startPtt, stopPtt]);

  const toggleWake = useCallback(async () => {
    const s = r.current;
    if (s.wake) { s.wake = false; setWake(false); s.seg?.flush(); idle(); return; }
    setError("");
    try { await openMic(); } catch (e) { setError(`Micrófono: ${(e as Error).message}`); return; }
    s.wake = true; setWake(true);
  }, [idle, openMic]);

  // texto transcrito -> orden
  useEffect(() => {
    if (!transcript) return;
    const mode = r.current.pending.get(transcript.id);
    if (!mode) return;
    r.current.pending.delete(transcript.id);
    if (r.current.pending.size === 0) setBusy(false);
    if (transcript.error) { setError(transcript.error); return; }
    const text = (transcript.text ?? "").trim();
    if (transcript.silent || !text) return;
    if (mode === "ptt") cb.current.onText(text);
    else { const m = matchWake(text); if (m.matched && m.rest) cb.current.onText(m.rest); }
  }, [transcript]);

  // síntesis de voz
  useEffect(() => {
    const syn = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!syn) return;
    const load = () => setVoices(syn.getVoices().map((v) => v.name));
    load(); syn.addEventListener?.("voiceschanged", load);
    return () => syn.removeEventListener?.("voiceschanged", load);
  }, []);
  const speak = useCallback((text: string) => {
    const syn = window.speechSynthesis;
    if (!syn || !settings.tts) return;
    const t = speakable(text);
    if (!t) return;
    syn.cancel();
    const u = new SpeechSynthesisUtterance(t);
    u.rate = settings.rate; u.lang = "es-ES";
    const v = syn.getVoices().find((x) => x.name === settings.voice) ?? syn.getVoices().find((x) => x.lang.toLowerCase().startsWith("es"));
    if (v) { u.voice = v; u.lang = v.lang; }
    u.onstart = () => { r.current.speaking = true; setSpeaking(true); };
    u.onend = u.onerror = () => { r.current.speaking = false; setSpeaking(false); };
    syn.speak(u);
  }, [settings]);
  const lastSpoken = useRef<number>(-1);
  useEffect(() => { if (lastAnswer && lastAnswer.key !== lastSpoken.current) { lastSpoken.current = lastAnswer.key; speak(lastAnswer.text); } }, [lastAnswer, speak]);
  useEffect(() => {                                                          // nivel simulado mientras habla (el navegador no da el audio de salida)
    if (!speaking) return;
    const id = window.setInterval(() => setLevel(0.25 + 0.35 * Math.abs(Math.sin(Date.now() / 140))), 80);
    return () => { window.clearInterval(id); setLevel(0); };
  }, [speaking]);

  const setSettings = useCallback((p: Partial<VoiceSettings>) => {
    setSettingsState((cur) => { const n = { ...cur, ...p }; save(n); if (!n.tts) window.speechSynthesis?.cancel(); return n; });
  }, []);
  const stopAll = useCallback(() => { r.current.ptt = r.current.wake = false; setPtt(false); setWake(false); window.speechSynthesis?.cancel(); closeMic(); }, [closeMic]);
  useEffect(() => stopAll, [stopAll]);                                        // al desmontar: micrófono cerrado

  return { supported, ptt, wake, busy, speaking, level, error, settings, voices, togglePtt, startPtt, stopPtt, toggleWake, setSettings, stopAll, dismissError: () => setError("") };
}
