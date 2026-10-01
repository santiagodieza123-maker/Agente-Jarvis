import { useCallback, useEffect, useReducer, useRef } from "react";
import { parseEvent, type HudMessage } from "./events";
import { initial, reduce } from "./store";

// Conexión: ?port=8765&token=... (en Tauri la inyecta el lanzador; en desarrollo se pasa a mano).
function endpoint(): string | null {
  const q = new URLSearchParams(location.search);
  const port = q.get("port"), token = q.get("token");
  return port && token ? `ws://127.0.0.1:${Number(port)}/?token=${encodeURIComponent(token)}` : null;
}

export function useJarvis() {
  const [state, dispatch] = useReducer(reduce, initial);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    const url = endpoint();
    if (!url) { dispatch({ kind: "conn", conn: "closed" }); return; }
    let stop = false, retry: number | undefined;
    const connect = () => {
      dispatch({ kind: "conn", conn: "connecting" });
      const s = new WebSocket(url);
      ws.current = s;
      const live = () => !stop && ws.current === s;  // ignora sockets obsoletos (StrictMode, reconexiones)
      s.onopen = () => { if (live()) dispatch({ kind: "conn", conn: "open" }); };
      s.onmessage = (m) => { const e = parseEvent(String(m.data)); if (e && live()) dispatch({ kind: "event", event: e }); };
      s.onclose = () => { if (!live()) return; dispatch({ kind: "conn", conn: "closed" }); retry = window.setTimeout(connect, 2000); };
    };
    connect();
    return () => { stop = true; window.clearTimeout(retry); ws.current?.close(); };
  }, []);

  const send = useCallback((m: HudMessage) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m));
  }, []);
  const submitTask = useCallback((goal: string) => { dispatch({ kind: "user", text: goal }); send({ type: "task", goal }); }, [send]);
  return { state, send, submitTask };
}
