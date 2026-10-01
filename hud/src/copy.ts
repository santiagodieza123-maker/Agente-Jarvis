import type { AgentState, Conn } from "./store";

/** Textos del HUD con voz propia. Los identificadores internos (estados, pestañas) no cambian: solo lo que se lee. */
export const STATE_LABEL: Record<AgentState, string> = {
  idle: "EN VELA", thinking: "CAVILANDO", acting: "MANOS A LA OBRA", awaiting: "ESPERO TU VISTO BUENO", error: "TROPEZÓN", killed: "APAGADO A LA FUERZA",
};
export const CONN_LABEL: Record<Conn, string> = { connecting: "DESPERTANDO…", open: "", closed: "SIN SEÑAL" };

export const TAB_LABEL: Record<string, string> = {
  consola: "CABINA", memoria: "RECUERDOS", permisos: "LLAVES", "auditoría": "BITÁCORA", mcp: "INJERTOS", "visión": "OJOS", sistema: "PULSO", config: "TALLER",
};

export const ORB_HINT: Record<AgentState, string> = {
  idle: "Toca la esfera: abre la estela de lo que hemos hecho",
  thinking: "Dándole vueltas al asunto…", acting: "Trabajando, no me mires así", awaiting: "Necesito tu permiso para seguir",
  error: "Algo salió mal; toca para ver qué", killed: "Frenado en seco",
};

export const EMPTY_TRAIL = "Todavía no hay estela. Pídeme algo y la esfera empezará a recordarlo.";
