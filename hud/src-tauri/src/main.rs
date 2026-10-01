#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{WebviewUrl, WebviewWindowBuilder};

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

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let script = connection_script(
                std::env::var("JARVIS_PORT").ok(),
                std::env::var("JARVIS_TOKEN").ok(),
            );
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
    use super::connection_script;

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
