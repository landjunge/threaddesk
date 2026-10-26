use std::{
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct Backend(Mutex<Child>);

/// The same workspace the rest of ThreadDesk already uses.
fn workspace_dir() -> PathBuf {
    let home = std::env::var_os("HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    home.join(".threaddesk")
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let data = workspace_dir();
            let binary = app.path().resource_dir()?.join("bin/ThreadDeskServer");
            if !binary.is_file() {
                return Err(format!("Backend missing: {}", binary.display()).into());
            }
            let mut child = Command::new(&binary)
                .env("THREADDESK_HOME", &data)
                .env("THREADDESK_STORAGE", "json")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()?;

            let stdout = child.stdout.take().ok_or("Backend stdout unavailable")?;
            let mut line = String::new();
            if BufReader::new(stdout).read_line(&mut line)? == 0 {
                let _ = child.wait();
                return Err("Backend exited without a ready URL".into());
            }
            let address = line.strip_prefix("THREADDESK_URL ").ok_or("Unexpected backend handshake")?.trim();
            let url: tauri::Url = address.parse()?;
            if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") || url.port().is_none() {
                return Err("Backend did not return a loopback-only address".into());
            }
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("ThreadDesk")
                .inner_size(1360.0, 900.0)
                .maximized(true)
                .min_inner_size(940.0, 640.0)
                .background_color(tauri::window::Color(13, 14, 19, 255))
                .build()?;
            app.manage(Backend(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(backend) = window.app_handle().try_state::<Backend>() {
                    if let Ok(mut child) = backend.0.lock() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("ThreadDesk Tauri runtime failed");
}

#[cfg(test)]
mod tests {
    use super::workspace_dir;

    #[test]
    fn workspace_is_the_home_store() {
        let home = std::env::var_os("HOME").expect("HOME");
        assert_eq!(workspace_dir(), std::path::PathBuf::from(home).join(".threaddesk"));
    }
}

