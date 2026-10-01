// Captura del micrófono: reenvía cada bloque de muestras (Float32) al hilo principal. Se carga desde 'self' (cumple la CSP de Tauri).
class MicCapture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("mic-capture", MicCapture);
