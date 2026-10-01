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
Arranque con un solo comando: `python tools/launch.py`. Lanza el núcleo (bajo el watchdog en Windows), espera `JARVIS_READY`
y abre el HUD de Tauri pasándole puerto y token por variables de entorno del proceso hijo (nunca por argv ni a logs; la clave de
Gemini se retira de ese entorno). Al cerrar el HUD el lanzador detiene el núcleo (en Windows, el Job Object del watchdog mata
además a todos sus hijos). Opciones: `--hud RUTA` o `JARVIS_HUD_BIN`, `--no-watchdog`, `--browser`.

Compilar el HUD: `cd hud && npm install && npm run tauri build` (el lanzador detecta `hud/src-tauri/target/release/jarvis-hud[.exe]`).
Desarrollo en navegador: `cd hud && npm run dev` y `python tools/launch.py --browser` (imprime y abre la URL con puerto y token).
La ventana no tiene bordes: la cabecera arrastra y trae minimizar, click-through y cerrar. Pruebas: `cd hud && npm test` y `cd hud/src-tauri && cargo test`.

Verificado en Linux: el binario de Tauri (release, bajo Xvfb) abre una conexión WebSocket establecida con el núcleo real usando el token
inyectado, y al cerrarlo no quedan procesos. **No** verificado: Windows (WebView2, arrastre/cierre/click-through reales, watchdog bajo el
lanzador). Límite: el token es visible, vía entorno del proceso, para procesos del mismo usuario (igual que lo sería por stdout).
Sin `GEMINI_API_KEY` el núcleo registra las tareas pero no las ejecuta.

## Configuración de Gemini y pestaña CONFIG
La clave puede ponerse en un `.env` en la raíz (ya está en `.gitignore`; no lo subas): `GEMINI_API_KEY=...`, o desde la pestaña CONFIG del HUD.
Prioridad: la clave guardada desde el HUD, y si no hay, la del entorno. La clave guardada va al Credential Manager de Windows si `keyring`
está instalado (`pip install -e .[windows]`) y, si no, a `~/.jarvis/secrets.json` (modo 0600). El HUD nunca recibe la clave, solo si existe y sus
4 últimos caracteres; tampoco se escribe en el log de auditoría (se audita el cambio, no el valor).

CONFIG permite, con efecto inmediato y persistente en `~/.jarvis/settings.json`: modelo (por defecto `gemini-3.1-flash-lite`, o `JARVIS_GEMINI_MODEL`),
pasos máximos (1–50), fallos acumulados (1–10), espera de aprobación (10–600 s), presupuesto de tokens por tarea (0 = sin límite; al agotarse la tarea
se aborta y queda auditado), color del HUD, mostrar el navegador del agente (al reiniciar), probar la conexión y ver el consumo de la sesión.
Todo se valida en el núcleo (todo o nada). El atajo de pánico (Ctrl+Shift+F10) lo fija el watchdog y se muestra solo como información.
Límites: con el archivo de secretos (sin keyring) un `shell.exec` aprobado por ti podría leerlo; el consumo se reinicia con cada arranque; no hay
selector de monitores (el actuador de GUI aún no existe). Raíces de archivos: `JARVIS_ROOTS` o pestaña PERMISOS.

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

## Auditoría (HUD)
Pestaña AUDITORÍA sobre `~/.jarvis/audit.jsonl` (cadena de hashes SHA-256): registros en vivo, filtro por evento, búsqueda, exportación,
y **Verificar cadena**, que indica la línea exacta donde se rompe. Consultar y verificar son solo lectura y no escriben en el log.
Límite conocido: sin clave, quien reescriba todo el archivo recalculando la cadena no se detecta; anota aparte la cabecera (`head`) que muestra el panel.
Un arranque con una línea parcial/corrupta ya no falla: se conserva y se señala como "(línea corrupta)".
