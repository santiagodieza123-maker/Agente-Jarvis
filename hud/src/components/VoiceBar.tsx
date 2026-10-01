import type { useVoice } from "../voice/useVoice";

type Voice = ReturnType<typeof useVoice>;

export function VoiceBar({ voice }: { voice: Voice }) {
  if (!voice.supported) return <div className="voicebar"><p className="hint" data-testid="voice-unsupported">La voz no está disponible: este equipo no permite capturar el micrófono.</p></div>;
  const rec = voice.ptt || voice.wake;
  return (
    <div className="voicebar" data-testid="voicebar">
      <div className="row">
        <button className={voice.ptt ? "on rec" : ""} onClick={voice.togglePtt} data-testid="mic-btn" aria-pressed={voice.ptt}
                title="Pulsa para empezar a hablar y otra vez para enviar (Ctrl+Espacio)">{voice.ptt ? "■ Enviar" : "🎙 Hablar"}</button>
        <label title="Escucha en segundo plano y actúa solo cuando la frase empieza por «Jarvis»"><input type="checkbox" checked={voice.wake} onChange={() => void voice.toggleWake()} data-testid="wake-toggle" /> Escucha continua («Jarvis, …»)</label>
        <label><input type="checkbox" checked={voice.settings.tts} onChange={(e) => voice.setSettings({ tts: e.target.checked })} data-testid="tts-toggle" /> Responder hablando</label>
        {rec && <span className="recdot" data-testid="rec-indicator" role="status">● micrófono abierto</span>}
        {voice.busy && <span className="hint">transcribiendo…</span>}
        {voice.speaking && <span className="hint">hablando…</span>}
      </div>
      {voice.settings.tts && voice.voices.length > 0 && (
        <div className="row">
          <select value={voice.settings.voice} onChange={(e) => voice.setSettings({ voice: e.target.value })} aria-label="Voz" data-testid="voice-select">
            <option value="">Voz por defecto (español)</option>
            {voice.voices.map((v) => <option key={v}>{v}</option>)}
          </select>
          <label className="rate">velocidad <input type="range" min={0.5} max={2} step={0.1} value={voice.settings.rate} onChange={(e) => voice.setSettings({ rate: Number(e.target.value) })} data-testid="rate" /></label>
        </div>
      )}
      {voice.error && <p className="warn" role="alert" data-testid="voice-error" onClick={voice.dismissError}>{voice.error}</p>}
      <p className="hint">El audio se envía a Google (Gemini) solo para transcribirlo; no se guarda. Lo dicho se trata como si lo hubieras escrito: pasa por los mismos permisos y confirmaciones.</p>
    </div>
  );
}
