use serde::Serialize;
use std::{
    env,
    ffi::OsString,
    net::TcpListener,
    path::{Path, PathBuf},
    sync::Mutex,
};
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

#[derive(Serialize)]
struct ApiError {
    code: String,
    message: String,
}

#[derive(Serialize)]
struct ApiEnvelope<T: Serialize> {
    ok: bool,
    data: Option<T>,
    error: Option<ApiError>,
}

#[derive(Serialize)]
struct RuntimeInfo {
    runtime: String,
    version: String,
}

#[derive(Serialize)]
struct RuntimeContext {
    runtime: String,
    version: String,
    backend_url: String,
}

struct BackendRuntime {
    backend_url: String,
    child: Mutex<Option<CommandChild>>,
}

impl BackendRuntime {
    fn spawn(app: &AppHandle) -> Result<Self, String> {
        let port = reserve_local_port().map_err(|error| {
            format!("无法为本地 backend 分配端口: {error}")
        })?;
        let backend_url = format!("http://127.0.0.1:{port}");
        let port_arg = OsString::from(port.to_string());
        let args = vec![
            OsString::from("--host"),
            OsString::from("127.0.0.1"),
            OsString::from("--port"),
            port_arg,
        ];

        let workspace_dir = workspace_root();
        let (mut events, child) = if cfg!(debug_assertions) {
            let backend_binary = find_dev_backend_binary().ok_or_else(|| {
                format!(
                    "找不到开发环境 backend，可检查 {} 下的 .venv",
                    workspace_dir.display()
                )
            })?;
            app.shell()
                .command(backend_binary.as_os_str())
                .args(args)
                .current_dir(&workspace_dir)
                .spawn()
                .map_err(|error| format!("启动开发 backend 失败: {error}"))?
        } else {
            app.shell()
                .sidecar("novel-backend")
                .map_err(|error| format!("创建 sidecar 命令失败: {error}"))?
                .args(args)
                .spawn()
                .map_err(|error| format!("启动 sidecar backend 失败: {error}"))?
        };

        let pid = child.pid();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = events.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        eprintln!(
                            "[novel-backend:{pid}:stdout] {}",
                            String::from_utf8_lossy(&line)
                        );
                    }
                    CommandEvent::Stderr(line) => {
                        eprintln!(
                            "[novel-backend:{pid}:stderr] {}",
                            String::from_utf8_lossy(&line)
                        );
                    }
                    CommandEvent::Error(message) => {
                        eprintln!("[novel-backend:{pid}:error] {message}");
                    }
                    CommandEvent::Terminated(payload) => {
                        eprintln!(
                            "[novel-backend:{pid}:terminated] code={:?} signal={:?}",
                            payload.code,
                            payload.signal
                        );
                        break;
                    }
                    _ => {}
                }
            }
        });

        Ok(Self {
            backend_url,
            child: Mutex::new(Some(child)),
        })
    }

    fn shutdown(&self) {
        if let Ok(mut child_guard) = self.child.lock() {
            if let Some(child) = child_guard.take() {
                let _ = child.kill();
            }
        }
    }
}

fn ok<T: Serialize>(data: T) -> ApiEnvelope<T> {
    ApiEnvelope {
        ok: true,
        data: Some(data),
        error: None,
    }
}

fn reserve_local_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")))
}

fn find_dev_backend_binary() -> Option<PathBuf> {
    let workspace_dir = workspace_root();
    let mut candidates = Vec::new();

    if let Ok(current_dir) = env::current_dir() {
        candidates.push(current_dir.join(".venv").join("bin").join("novel-backend"));
        candidates.push(
            current_dir
                .join(".venv")
                .join("Scripts")
                .join("novel-backend.exe"),
        );

        if let Some(parent_dir) = current_dir.parent() {
            candidates.push(parent_dir.join(".venv").join("bin").join("novel-backend"));
            candidates.push(
                parent_dir
                    .join(".venv")
                    .join("Scripts")
                    .join("novel-backend.exe"),
            );
        }
    }

    candidates.push(workspace_dir.join(".venv").join("bin").join("novel-backend"));
    candidates.push(
        workspace_dir
            .join(".venv")
            .join("Scripts")
            .join("novel-backend.exe"),
    );

    candidates.into_iter().find(|path| path.exists())
}

#[tauri::command]
fn get_app_version(app: tauri::AppHandle) -> ApiEnvelope<RuntimeInfo> {
    ok(RuntimeInfo {
        runtime: "tauri".to_string(),
        version: app.package_info().version.to_string(),
    })
}

#[tauri::command]
fn get_runtime_context(
    app: tauri::AppHandle,
    backend: tauri::State<'_, BackendRuntime>,
) -> ApiEnvelope<RuntimeContext> {
    ok(RuntimeContext {
        runtime: "tauri".to_string(),
        version: app.package_info().version.to_string(),
        backend_url: backend.backend_url.clone(),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let backend = BackendRuntime::spawn(&app.handle()).map_err(|message| {
                std::io::Error::new(std::io::ErrorKind::Other, message)
            })?;
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_app_version,
            get_runtime_context
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            let backend = app_handle.state::<BackendRuntime>();
            backend.shutdown();
        }
    });
}
