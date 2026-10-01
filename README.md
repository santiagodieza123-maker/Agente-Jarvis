# Agente Jarvis

Agente de uso de computadora (CUA) para Windows con HUD estilo Jarvis (Tauri + React/Three.js).
Plan completo: ver fases 0–7. Estado: Fases 0–1 hechas (sin probar en Windows); Fase 2: bus, servidor WS, orquestador, HUD y herramientas de archivos conectados entre sí; falta el proveedor LLM real.

- `watchdog/` kill switch independiente (Job Object + Ctrl+Shift+F10), solo Windows
- `actuators/` entrada Win32 (`SendInput`), solo Windows
- `core/` herramientas de archivos acotadas (`JARVIS_ROOTS`, por defecto `~/Jarvis`), `core/app.py` (ensamblado), políticas, auditoría encadenada, `LLMProvider`, bus de eventos, servidor WS autenticado (`python -m core.main`)
- `schemas/` contrato de eventos HUD↔core
- `hud/` HUD Tauri + React + Three.js: orbe con estados, consola, línea de tiempo de acciones, aprobaciones y botón de pánico
- `perception/`, `broker/` pendientes

Pruebas portables: `pip install -e .[dev] && pytest`. El código Win32 requiere Windows para ejecutarse.

## HUD
Desarrollo: arranca `python -m core.main` (imprime `port` y `token`) y `cd hud && npm install && npm run dev`;
abre `http://localhost:1420/?port=<port>&token=<token>`. Pruebas: `cd hud && npm test`.
Pendiente de verificar: el shell de Tauri (`hud/src-tauri`) no se ha compilado (requiere Windows/Rust y `tauri icon`);
el lanzador que pasa puerto y token al HUD; `core.app.load_llm()` devuelve `None` hasta implementar el proveedor Gemini: sin LLM el núcleo registra las tareas pero no las ejecuta.
