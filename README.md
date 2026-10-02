# Agente Jarvis

Agente de uso de computadora (CUA) para Windows con HUD estilo Jarvis (Tauri + React/Three.js).
Estado: las diez funciones del plan están implementadas (ver «Funciones»). Verificado en Linux, con el modelo real y Chromium, y en runners de Windows
(CI); lo que no puede comprobarse sin tu máquina se lista en «Límites».

- `watchdog/` kill switch independiente (Job Object + Ctrl+Shift+F10), solo Windows
- `actuators/` entrada Win32 (`SendInput`: clics, texto Unicode, combinaciones), solo Windows
- `perception/` UI Automation (ventanas, elementos numerados, Set-of-Marks) detrás de una interfaz `GuiBackend`
- `core/` herramientas de shell (siempre con aprobación), navegador (Playwright, perfil dedicado, anti-SSRF), archivos acotados (`JARVIS_ROOTS`, por defecto `~/Jarvis`),
  GUI, recetas, extensiones MCP, políticas, auditoría encadenada, `LLMProvider`, bus de eventos, servidor WS autenticado (`python -m core.main`)
- `broker/` servicio elevado de operaciones cerradas (solo Windows)
- `schemas/` contrato de eventos HUD↔core
- `hud/` HUD Tauri + React + Three.js

Pruebas portables: `pip install -e .[dev] && pytest`. El código Win32 requiere Windows para ejecutarse.

## HUD
Arranque con un solo comando: `python tools/launch.py`. Lanza el núcleo (bajo el watchdog en Windows), espera `JARVIS_READY`
y abre el HUD de Tauri entregándole puerto y token por su **entrada estándar** (una línea JSON): no quedan en argv ni en el entorno del proceso,
donde otro proceso del mismo usuario podría leerlos; la clave de Gemini tampoco llega al HUD. Al cerrar el HUD el lanzador detiene el núcleo
(en Windows, el Job Object del watchdog mata además a todos sus hijos). Opciones: `--hud RUTA` o `JARVIS_HUD_BIN`, `--no-watchdog`, `--browser`, `--no-admin` (en Windows el lanzador se eleva como administrador por defecto; para abrirlo sin aviso UAC ejecuta una vez `toolsinstall_admin_shortcut.ps1` como administrador: crea la tarea programada «Jarvis» y un acceso directo en el escritorio).

Compilar el HUD: `cd hud && npm install && npm run tauri build` (el lanzador detecta `hud/src-tauri/target/release/jarvis-hud[.exe]`).
Desarrollo en navegador: `cd hud && npm run dev` y `python tools/launch.py --browser` (imprime y abre la URL con puerto y token).
La ventana no tiene bordes: la cabecera arrastra y trae minimizar, click-through y cerrar. **Ctrl+Shift+F9** activa/desactiva el click-through
aunque la ventana no reciba clics, y el HUD lo desactiva solo cuando hay una aprobación pendiente. Pruebas: `cd hud && npm test`, `cd hud/src-tauri && cargo test`.

**Estela:** tocar la esfera abre el historial de tareas (buscar, repetir con un clic, copiar la respuesta). Los textos del HUD viven en `hud/src/copy.ts` y en cada panel.

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
No hay selector de monitores (la GUI usa el escritorio virtual completo). Raíces de archivos: `JARVIS_ROOTS` o pestaña PERMISOS.
Restringe la clave en Google AI Studio (solo la API Generative Language) para limitar el daño si algún día se filtra. Ante un 429 de cuota Jarvis espera lo que
indica el servidor (máx. 45 s por reintento, 3 reintentos) y avisa en la consola; si la cuota está agotada falla con un mensaje claro.

## Funciones

### Control de la GUI (UI Automation)
`pip install -e .[windows]`. Herramientas `gui.windows`, `gui.observe`, `gui.focus`, `gui.click`, `gui.type`, `gui.press` y `gui.click_xy`. `gui.observe` lista los
elementos de la ventana con **números estables** (Set-of-Marks): el modelo dice «clic en 12», nunca coordenadas; si el elemento cambió o se movió desde la
observación, el clic se rechaza y hay que volver a observar. Se usan los patrones de UIA (Invoke, Toggle, SelectionItem, ExpandCollapse, Value) y solo si no hay uno se
hace un clic con `SendInput`. Con `image=true` la captura anotada se entrega al modelo (visión) una vez, en la siguiente llamada.
Reglas de seguridad: todo lo que devuelve la GUI es **no confiable** (activa la confirmación de escrituras posteriores); los campos de contraseña nunca se leen ni se
rellenan; el HUD de Jarvis es invisible e intocable para el agente (la ventana tiene `content_protected` y se filtra por proceso/título, de modo que no puede pulsar
«Permitir»); `gui.press` solo admite una lista de teclas/combinaciones seguras; `gui.click_xy` es DESTRUCTIVA (siempre confirma). La pestaña VISIÓN muestra la
captura con las cajas numeradas y la acción en curso.

**Detección visual (OmniParser v2).** `pip install -e .[vision]` (con torch CUDA: `pip install torch --index-url https://download.pytorch.org/whl/cu128`).
Añade `gui.detect` (YOLO localiza botones/iconos en la captura de la ventana y Florence-2 los describe → elementos `v1`, `v2`… con imagen anotada) y
`gui.click_visual` (clic en el centro de un `vN`, con las mismas protecciones que `gui.click_xy`; tras actuar hay que volver a detectar). Para juegos, apps de
dibujo y Electron sin árbol de accesibilidad. Pesos (~1 GB, `microsoft/OmniParser-v2.0`; icon_detect AGPL-3.0, icon_caption MIT) en `~/.jarvis/models/omniparser`,
descargados la primera vez. Recomendado GPU NVIDIA; en CPU funciona pero tarda.

### Recetas ejecutables
En MEMORIA, un episodio terminado puede guardarse como receta («Guardar receta»; solo el usuario, no el agente). Los pasos GUI se guardan por nombre/rol/orden, no por
número. Se pueden parametrizar con `{{parametro}}` (con valor por defecto) y añadir precondiciones (`path_exists`, `window_contains`). Reproducir una receta **no llama al
LLM**: cada paso pasa por la misma política, confirmaciones, reglas de contenido no confiable y verificación; se detiene en el primer fallo y registra tasa de éxito. Una
receta no concede permisos. Si se creó tras leer contenido no confiable se marca con aviso.

### Voz
Pulsar para hablar (Ctrl+Espacio) o escucha continua que solo actúa ante «Jarvis, …». Indicador de micrófono siempre visible; la voz de respuesta usa la síntesis del
navegador (voz y velocidad configurables) y el nivel del micrófono mueve el orbe. **Privacidad:** con `pip install -e .[voice]` el audio se transcribe
en local con Whisper (faster-whisper; `large-v3-turbo` en GPU, `small` en CPU; `JARVIS_WHISPER_MODEL`/`JARVIS_WHISPER_LANG`) y no sale del equipo; ajuste «Voz local»
en CONFIG (activo por defecto; si falla no recurre a Google). Sin Whisper o con el ajuste desactivado, el audio se envía a Google (Gemini), limitado a 20 peticiones/min.
El núcleo acepta WAV ≤4 MB y no guarda ni audita el audio ni el texto (solo bytes y caracteres).

### Panel SISTEMA y apariencia
SISTEMA: CPU y memoria de Jarvis y sus hijos, retraso del bucle de eventos, GPU (`nvidia-smi` si existe), latencia y errores del modelo, salud de cada componente (núcleo,
modelo, navegador, UIA, watchdog, extensiones, broker) y procesos hijos; solo se muestrea mientras haya un HUD conectado. Orbe con bloom y partículas, parallax, modo
compacto (orbe + estado + pánico; las aprobaciones siguen apareciendo) y seis temas (cian, ámbar, verde, magenta, rojo, hielo); sin WebGL se usa un reactor CSS.

### Broker elevado
El agente corre con integridad Medium. Para operaciones que necesitan administrador existe un proceso aparte (`python -m broker.service`, lanzado desde PERMISOS con
**Iniciar**, que provoca el aviso UAC de Windows). Habla por un named pipe con ACL solo para tu usuario y SYSTEM (sin acceso remoto; solo la primera instancia del
pipe es válida), con peticiones firmadas con HMAC, frescas (30 s) y sin repetición. Solo existen operaciones **cerradas**: `winget_install {id}`,
`service_control {name, start|stop|restart|status}` sobre servicios de una lista permitida que solo se amplía desde el HUD (con doble confirmación), y `ping`/`shutdown`.
No hay shell ni argumentos libres. Cada operación que cambia algo exige además un cuadro de diálogo del propio servicio elevado (por defecto «No»; UIPI impide que
un proceso Medium lo pulse), 6 operaciones/min como máximo, y todo se registra. La herramienta del agente es `elevated.*` (clase ELEVATED). `--insecure-auto-approve`
existe solo para pruebas y no se usa nunca desde el HUD. Fuera de alcance: el escritorio seguro (UAC, Ctrl+Alt+Supr).

## Límites conocidos
- **Comprobado en hardware real** (Windows 11, 1 monitor 1920×1080 al 100 %, integridad Medium): clic exacto con SendInput, watchdog, shell, WebSocket y navegador.
  Solo se soporta/valida un monitor; varios monitores y escalado 125/150 % no están verificados.
- **Broker comprobado con una persona** (UAC, `ping`, `winget_install` real, `service_control` sobre Spooler, y denegación: al pulsar «No» no se ejecuta nada).
- La detección visual (OmniParser) no lee texto con OCR: las descripciones de Florence-2 son aproximadas y el modelo debe contrastarlas con la imagen.
- Sin Whisper local, el audio de la voz sale hacia Google; la escucha continua depende de la calidad del micrófono y de la transcripción.
- Un `shell.exec` aprobado por ti puede hacer lo que tu usuario puede hacer: la barrera es tu confirmación.

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
  El agente puede guardar notas con `memory.remember` (escritura reversible); si ya leyó contenido no confiable, pide confirmación (evita envenenarla).
- **Permisos:** confirmación por clase (lectura y escritura reversible configurables; destructiva y elevada **siempre** piden confirmación),
  herramientas activables y carpetas accesibles. Se rechazan carpetas demasiado amplias, del sistema, tu carpeta personal y la del repo/config
  de Jarvis (contienen la clave y los permisos). Ninguna herramienta del agente puede modificar estos ajustes.
- **Modo autónomo** (casilla en LLAVES, desactivado por defecto): ninguna acción pide confirmación —tampoco destructivas, elevadas ni las
  originadas por contenido no confiable— y los archivos son accesibles en cualquier ruta salvo el repo y `~/.jarvis`. Todo sigue auditado.
  Riesgo: una web o archivo con instrucciones ocultas puede hacer que Jarvis actúe sin que lo veas.

## Auditoría (HUD)
Pestaña AUDITORÍA sobre `~/.jarvis/audit.jsonl` (cadena de hashes SHA-256): registros en vivo, filtro por evento, búsqueda, exportación,
y **Verificar cadena**, que indica la línea exacta donde se rompe. Consultar y verificar son solo lectura y no escriben en el log.
Con HMAC (por defecto: la clave vive en el almacén de secretos, no junto al log) cada registro lleva `mac`, de modo que reescribir el archivo recalculando la
cadena no es posible sin la clave; `~/.jarvis/audit.anchor` (también autenticado) detecta truncados y un log autenticado no puede degradarse a uno sin mac. Si al
arrancar falta algo respecto al ancla se añade un registro permanente `audit.tamper_detected`. Un log anterior sin mac se migra solo la primera vez.
Exportar escribe los registros completos del filtro actual en `~/.jarvis/exports/` (JSONL). Límite: quien tenga acceso a la clave HMAC y al archivo (mismo usuario con
código propio) podría rehacerlo todo; con keyring en Windows la clave no está en un archivo.
Un arranque con una línea parcial/corrupta ya no falla: se conserva y se señala como "(línea corrupta)".
