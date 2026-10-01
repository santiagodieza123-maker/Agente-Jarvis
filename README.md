# Agente Jarvis

Agente de uso de computadora (CUA) para Windows con HUD estilo Jarvis (Tauri + React/Three.js).
Plan completo: ver fases 0–7. Estado: Fases 0–1 (cimientos y seguridad base) en curso.

- `watchdog/` kill switch independiente (Job Object + Ctrl+Shift+F10), solo Windows
- `actuators/` entrada Win32 (`SendInput`), solo Windows
- `core/` políticas, auditoría encadenada, interfaz `LLMProvider`
- `schemas/` contrato de eventos HUD↔core
- `perception/`, `broker/`, `hud/` pendientes

Pruebas portables: `pip install -e .[dev] && pytest`. El código Win32 requiere Windows para ejecutarse.
