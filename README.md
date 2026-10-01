# Agente Jarvis

Agente de uso de computadora (CUA) para Windows con HUD estilo Jarvis (Tauri + React/Three.js).
Plan completo: ver fases 0–7. Estado: Fases 0–1 hechas (sin probar en Windows); Fase 2: bus, servidor WS, orquestador, HUD y herramientas de archivos conectados entre sí; proveedor Gemini (`gemini-3.1-flash-lite`) implementado y probado en vivo.

- `watchdog/` kill switch independiente (Job Object + Ctrl+Shift+F10), solo Windows
- `actuators/` entrada Win32 (`SendInput`), solo Windows
- `core/` herramientas de shell (siempre con aprobación) y navegador (Playwright, perfil dedicado, anti-SSRF), herramientas de archivos acotadas (`JARVIS_ROOTS`, por defecto `~/Jarvis`), `core/app.py` (ensamblado), políticas, auditoría encadenada, `LLMProvider`, bus de eventos, servidor WS autenticado (`python -m core.main`)
- `schemas/` contrato de eventos HUD↔core
- `hud/` HUD Tauri + React + Three.js: orbe con estados, consola, línea de tiempo de acciones, aprobaciones y botón de pánico
- `perception/`, `broker/` pendientes

Pruebas portables: `pip install -e .[dev] && pytest`. El código Win32 requiere Windows para ejecutarse.

## HUD
Desarrollo: arranca `python -m core.main` (imprime `port` y `token`) y `cd hud && npm install && npm run dev`;
abre `http://localhost:1420/?port=<port>&token=<token>`. Pruebas: `cd hud && npm test`.
Verificado: el shell de Tauri compila (`cargo check`, en Linux; no se ha ejecutado ni empaquetado en Windows). Pendiente:
el lanzador que pasa puerto y token al HUD; Sin `GEMINI_API_KEY` el núcleo registra las tareas pero no las ejecuta.

## Configuración de Gemini
Crea un `.env` en la raíz (ya está en `.gitignore`; no lo subas): `GEMINI_API_KEY=...`.
Modelo por defecto `gemini-3.1-flash-lite`; cámbialo con `JARVIS_GEMINI_MODEL`. Raíces de archivos: `JARVIS_ROOTS`.

## Navegador y shell
`pip install -e .[web] && playwright install chromium`. El navegador usa un perfil propio (`~/.jarvis/browser-profile`, o `JARVIS_BROWSER_PROFILE`),
visible con `JARVIS_BROWSER_HEADED=1`. Bloquea localhost, redes privadas, metadatos cloud y esquemas no http(s), incluso tras redirecciones.
Límite conocido: DNS rebinding entre la comprobación y la conexión no está cubierto. `shell.exec` pide aprobación cada vez y no hereda
variables con KEY/TOKEN/SECRET/PASSWORD en el nombre.

## Verificación en Windows
Lo que no se puede ejecutar en Linux (clics en varios monitores, watchdog, PowerShell, WebView2) se prueba con un script.
En una terminal **normal** (no elevada), desde la raíz del repo:

    py -3.11 -m venv .venv ; .venv\Scripts\activate
    pip install -e ".[web]" ; playwright install chromium
    python tools/verify_windows.py

Tarda ~40 s y mueve el cursor: no toques mouse ni teclado. Genera `verify_report.txt` (y `.json`), sin claves ni variables de entorno.

## Memoria y permisos (HUD)
Pestañas MEMORIA y PERMISOS. Se guardan en `~/.jarvis` (`JARVIS_HOME`): `memory.db` (SQLite) y `permissions.json`.
- **Memoria:** notas (preferencia/dato) que solo el usuario crea desde el HUD y que Jarvis recibe como contexto (no como órdenes); historial de tareas.
  El agente no puede escribir memoria por su cuenta (evita envenenarla con contenido leído de la web).
- **Permisos:** confirmación por clase (lectura y escritura reversible configurables; destructiva y elevada **siempre** piden confirmación),
  herramientas activables y carpetas accesibles. Se rechazan carpetas demasiado amplias, del sistema, tu carpeta personal y la del repo/config
  de Jarvis (contienen la clave y los permisos). Ninguna herramienta del agente puede modificar estos ajustes.
