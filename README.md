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
y abre el HUD de Tauri entregándole puerto y token por su **entrada estándar** (una línea JSON): no quedan en argv ni en el entorno del proceso,
donde otro proceso del mismo usuario podría leerlos; la clave de Gemini tampoco llega al HUD. Al cerrar el HUD el lanzador detiene el núcleo
(en Windows, el Job Object del watchdog mata además a todos sus hijos). Opciones: `--hud RUTA` o `JARVIS_HUD_BIN`, `--no-watchdog`, `--browser`.

Compilar el HUD: `cd hud && npm install && npm run tauri build` (el lanzador detecta `hud/src-tauri/target/release/jarvis-hud[.exe]`).
Desarrollo en navegador: `cd hud && npm run dev` y `python tools/launch.py --browser` (imprime y abre la URL con puerto y token).
La ventana no tiene bordes: la cabecera arrastra y trae minimizar, click-through y cerrar. **Ctrl+Shift+F9** activa/desactiva el click-through
aunque la ventana no reciba clics, y el HUD lo desactiva solo cuando hay una aprobación pendiente. Pruebas: `cd hud && npm test`, `cd hud/src-tauri && cargo test`.

## Verificación continua (CI)
`.github/workflows/ci.yml` ejecuta en cada push, en Linux **y en Windows** (runners reales de GitHub): `pytest`, tipos/`vitest`/build del HUD,
`cargo test`, escaneo de secretos, `tools/verify_windows.py` (watchdog, SendInput, PowerShell, WebSocket, Playwright, WebView2), la compilación del HUD de
Tauri en Windows y una prueba extremo a extremo con el binario real (lanzador + watchdog + Tauri/WebView2 + conexión autenticada + atajo de click-through
enviado con SendInput). En CI la sesión corre con integridad High (administrador); el diseño exige Medium en uso normal.
Hook local contra fugas de claves: `python tools/install_hooks.py`.

## Configuración de Gemini y pestaña CONFIG
La clave puede ponerse en un `.env` en la raíz (ya está en `.gitignore`; no lo subas): `GEMINI_API_KEY=...`, o desde la pestaña CONFIG del HUD.
Prioridad: la clave guardada desde el HUD, y si no hay, la del entorno. La clave guardada va al Credential Manager de Windows si `keyring`
está instalado (`pip install -e .[windows]`) y, si no, a `~/.jarvis/secrets.json` (modo 0600). El HUD nunca recibe la clave, solo si existe y sus
4 últimos caracteres; tampoco se escribe en el log de auditoría (se audita el cambio, no el valor).

CONFIG permite, con efecto inmediato y persistente en `~/.jarvis/settings.json`: modelo (por defecto `gemini-3.1-flash-lite`, o `JARVIS_GEMINI_MODEL`),
pasos máximos (1–50), fallos acumulados (1–10), espera de aprobación (10–600 s), presupuesto de tokens por tarea (0 = sin límite; al agotarse la tarea
se aborta y queda auditado), color del HUD, mostrar el navegador del agente (al reiniciar), probar la conexión y ver el consumo de la sesión.
Todo se valida en el núcleo (todo o nada). El atajo de pánico (Ctrl+Shift+F10) lo fija el watchdog y se muestra solo como información.
Con el archivo de secretos (sin keyring) un `shell.exec` aprobado por ti podría leerlo: la aprobación muestra una advertencia roja si el comando o la ruta
toca `~/.jarvis`, `.env`, claves SSH/nube o el administrador de credenciales. El consumo (sesión, hoy, total) persiste en `~/.jarvis/usage.json`.
No hay selector de monitores (el actuador de GUI aún no existe). Raíces de archivos: `JARVIS_ROOTS` o pestaña PERMISOS.
Restringe la clave en Google AI Studio (solo la API Generative Language) para limitar el daño si algún día se filtra. Ante un 429 de cuota Jarvis espera lo que
indica el servidor (máx. 45 s por reintento, 3 reintentos) y avisa en la consola; si la cuota está agotada falla con un mensaje claro.

## Extensiones (MCP)
`pip install -e .[mcp]`. La pestaña MCP da de alta servidores MCP por stdio (p. ej. `npx -y @modelcontextprotocol/server-everything`); sus herramientas
aparecen como `mcp.<extensión>.<herramienta>`. Un servidor MCP es código externo que se ejecuta con tus permisos, así que:
solo el HUD puede darlo de alta (con diálogo que muestra el comando exacto; el agente no puede); se lanza sin shell, con entorno mínimo (sin la clave de
Gemini ni variables KEY/TOKEN/SECRET) y con la primera raíz de trabajo como directorio; sus herramientas piden **confirmación siempre** (clase DESTRUCTIVE)
hasta que marques una concreta como «lectura»; su salida se trata como **no confiable** (tras leerla, cualquier escritura posterior pide confirmación);
la descripción que declara el servidor se reduce a su primera línea (≤160 caracteres) y su esquema a una lista blanca; resultados ≤20 000 caracteres y 60 s por llamada.
Las activadas arrancan con el núcleo; con el pánico o al cerrar el núcleo (SIGTERM/Ctrl+C) o el HUD se terminan sus procesos. Estado y registro de errores en el panel.
Variables de entorno por extensión (p. ej. un token): se guardan en el almacén de secretos, nunca en `extensions.json`, en el log ni en el HUD (solo se ven los
nombres). Mientras haya herramientas MCP activas, **las escrituras piden confirmación** (ajuste «Confirmar escrituras con extensiones activas», por defecto
activo), de modo que una descripción maliciosa no puede originar escrituras sin que lo veas. Compatible con `mcp` 1.x y 2.x. Variable `JARVIS_CORE_PORT` (por
defecto 8765; 0 = aleatorio).

## Navegador y shell
`pip install -e .[web] && playwright install chromium`. El navegador usa un perfil propio (`~/.jarvis/browser-profile`, o `JARVIS_BROWSER_PROFILE`),
visible con `JARVIS_BROWSER_HEADED=1`. Bloquea localhost, redes privadas, metadatos cloud y esquemas no http(s), incluso tras redirecciones.
Todo el tráfico del navegador pasa por un **proxy de salida local** (`core/egress_proxy.py`) que resuelve el destino una sola vez, rechaza cualquier IP no pública
(loopback, privadas, link-local, metadatos, IPv4 en IPv6) y conecta a esa misma IP ya validada: sin ventana de DNS rebinding y con redirecciones, subrecursos y
WebSockets cubiertos (WebRTC UDP desactivado). Los túneles HTTPS no se inspeccionan. `shell.exec` pide aprobación cada vez y no hereda variables con
KEY/TOKEN/SECRET/PASSWORD en el nombre. Las rutas relativas que propone el modelo se resuelven dentro de la carpeta de trabajo, que se le indica en el prompt.

## Verificación en Windows
Se ejecuta sola en CI (ver arriba). En tu máquina, en una terminal **normal** (no elevada), para comprobar además el nivel de integridad Medium, varios monitores y escalado:

    py -3.11 -m venv .venv ; .venv\Scripts\activate
    pip install -e ".[web,windows]" ; playwright install chromium
    python tools/verify_windows.py

Tarda ~40 s y mueve el cursor: no toques mouse ni teclado. Genera `verify_report.txt` (y `.json`), sin claves ni variables de entorno.
Resultado en CI (Windows 11, 1 monitor al 100 %): 10 OK, 0 FAIL; solo avisa del nivel de integridad (el runner es administrador).

## Evaluación con el modelo real
`python tools/eval.py` (necesita `GEMINI_API_KEY`) ejecuta 11 tareas reproducibles (archivos, borrado con y sin aprobación, ruta fuera de la carpeta,
inyección en un archivo, memoria, extensión MCP) y mide éxito, pasos, tokens y segundos (`eval_report.md`). Última ejecución con `gemini-3.1-flash-lite`:
**11/11**, unos 19 000 tokens en total. Las llamadas a herramientas se envían a Gemini en formato nativo (`functionCall`/`functionResponse` con la firma de
pensamiento); con historial en texto el modelo imitaba el formato en lugar de llamar a la herramienta (fallo detectado por esta evaluación).

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
Con HMAC (por defecto: la clave vive en el almacén de secretos, no junto al log) cada registro lleva `mac`, de modo que reescribir el archivo recalculando la
cadena no es posible sin la clave; `~/.jarvis/audit.anchor` (también autenticado) detecta truncados y un log autenticado no puede degradarse a uno sin mac. Si al
arrancar falta algo respecto al ancla se añade un registro permanente `audit.tamper_detected`. Un log anterior sin mac se migra solo la primera vez.
Exportar escribe los registros completos del filtro actual en `~/.jarvis/exports/` (JSONL). Límite: quien tenga acceso a la clave HMAC y al archivo (mismo usuario con
código propio) podría rehacerlo todo; con keyring en Windows la clave no está en un archivo.
Un arranque con una línea parcial/corrupta ya no falla: se conserva y se señala como "(línea corrupta)".
