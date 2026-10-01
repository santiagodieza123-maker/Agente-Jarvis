#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, IsTerminal};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::time::Duration;
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// Estado del modo click-through (el ratón atraviesa la ventana). Se puede salir de él con Ctrl+Shift+F9 aunque la
/// ventana no reciba clics, y el HUD lo desactiva solo cuando hay una aprobación pendiente.
struct ClickThrough(AtomicBool);

fn apply_click_through(app: &tauri::AppHandle, enabled: bool) {
    if let Some(w) = app.get_webview_window("main") {
        if w.set_ignore_cursor_events(enabled).is_ok() {
            app.state::<ClickThrough>().0.store(enabled, Ordering::SeqCst);
            let _ = app.emit("click-through", enabled);
        }
    }
}

#[tauri::command]
fn set_click_through(app: tauri::AppHandle, enabled: bool) {
    apply_click_through(&app, enabled);
}


/// Script que expone al HUD el puerto y el token que el lanzador entregó por entorno.
/// Se serializa con serde_json: el token nunca se interpola como código.
fn connection_script(port: Option<String>, token: Option<String>) -> String {
    match (port.and_then(|p| p.parse::<u16>().ok()), token.filter(|t| !t.is_empty())) {
        (Some(port), Some(token)) => format!(
            "window.__JARVIS__ = Object.freeze({});",
            serde_json::json!({ "port": port, "token": token })
        ),
        _ => String::new(),
    }
}

/// Interpreta la línea JSON `{"port": N, "token": "…"}` que entrega el lanzador por la entrada estándar.
fn parse_connection(line: &str) -> Option<(String, String)> {
    let v: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let port = v.get("port")?.as_u64().filter(|p| (1..=65535).contains(p))?;
    let token = v.get("token")?.as_str().filter(|t| !t.is_empty() && t.len() <= 256)?;
    Some((port.to_string(), token.to_string()))
}

/// El token llega por stdin (no por entorno ni argv, que otros procesos del usuario pueden leer).
/// Sin tubería (terminal interactiva) no se espera nada; con tubería se espera hasta 5 s.
fn connection_from_stdin() -> Option<(String, String)> {
    if std::io::stdin().is_terminal() {
        return None;
    }
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let _ = std::io::stdin().lock().read_line(&mut line);
        let _ = tx.send(line);
    });
    parse_connection(&rx.recv_timeout(Duration::from_secs(5)).ok()?)
}

fn main() {
    tauri::Builder::default()
        .manage(ClickThrough(AtomicBool::new(false)))
        .invoke_handler(tauri::generate_handler![set_click_through])
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        let now = app.state::<ClickThrough>().0.load(Ordering::SeqCst);
                        apply_click_through(app, !now);
                    }
                })
                .build(),
        )
        .setup(|app| {
            let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F9);
            if let Err(e) = app.global_shortcut().register(toggle) {
                eprintln!("no se pudo registrar Ctrl+Shift+F9 (click-through): {e}");   // otra app lo usa; el HUD sigue funcionando
            }
            // Prioridad: stdin (lanzador); como alternativa manual, las variables JARVIS_PORT / JARVIS_TOKEN.
            let (port, token) = match connection_from_stdin() {
                Some((p, t)) => (Some(p), Some(t)),
                None => (std::env::var("JARVIS_PORT").ok(), std::env::var("JARVIS_TOKEN").ok()),
            };
            let script = connection_script(port, token);
            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Jarvis")
                .inner_size(1100.0, 700.0)
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .resizable(true)
                .initialization_script(script)
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error al iniciar el HUD de Jarvis");
}

#[cfg(test)]
mod tests {
    use super::{connection_script, parse_connection};

    #[test]
    fn parsea_la_linea_de_stdin() {
        assert_eq!(parse_connection("{\"port\": 8765, \"token\": \"abc\"}\n"), Some(("8765".into(), "abc".into())));
        for bad in ["", "no json", "{}", "{\"port\": 0, \"token\": \"a\"}", "{\"port\": 70000, \"token\": \"a\"}",
                    "{\"port\": \"80\", \"token\": \"a\"}", "{\"port\": 80, \"token\": \"\"}", "{\"port\": 80, \"token\": 5}"] {
            assert_eq!(parse_connection(bad), None, "{bad}");
        }
        let largo = format!("{{\"port\": 80, \"token\": \"{}\"}}", "x".repeat(300));
        assert_eq!(parse_connection(&largo), None);
    }

    #[test]
    fn sin_variables_no_define_nada() {
        assert_eq!(connection_script(None, None), "");
        assert_eq!(connection_script(Some("8765".into()), None), "");
        assert_eq!(connection_script(Some("x".into()), Some("t".into())), "");
        assert_eq!(connection_script(Some("8765".into()), Some("".into())), "");
    }

    #[test]
    fn el_token_se_escapa_como_json() {
        let s = connection_script(Some("8765".into()), Some("a\"; alert(1); //".into()));
        assert!(s.starts_with("window.__JARVIS__ = Object.freeze({"));
        assert!(s.contains("\\\"; alert(1)"));
        assert!(s.contains("\"port\":8765"));
    }
}
