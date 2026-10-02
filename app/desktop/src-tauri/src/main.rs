#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashMap, path::PathBuf, process::Stdio, sync::{Arc, atomic::{AtomicBool, AtomicU64, Ordering}}, time::Duration};
use tauri::{Emitter, Manager};
use tokio::{io::{AsyncBufReadExt, AsyncWriteExt, BufReader}, process::{Child, ChildStdin, Command}, sync::{Mutex, oneshot}};

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum Provider { Line, Instagram, Slack }

#[derive(Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case", rename_all_fields = "camelCase", deny_unknown_fields)]
enum CoreRequest {
    Snapshot { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    LineLoginStart { replace: bool },
    LineLoginStatus,
    LineLoginCancel,
    Avatar { conversation_id: String },
    Connect { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    Select { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String },
    Messages { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String },
    Refresh { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    Stop { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    Search { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, query: String },
    Send { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String, text: String, request_id: String },
    Management { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    McpConfigure { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, enabled: bool, port: u16 },
    McpRegister { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, name: String, conversation_ids: Vec<String>, read: bool, send: bool },
    McpRevoke { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, client_id: String },
    StoragePause { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, paused: bool },
    StorageDeletePreview,
    StorageDelete { confirmation: String },
}

type Reply = Result<Value, String>;

struct Bridge {
    input: Mutex<Option<ChildStdin>>,
    child: Mutex<Child>,
    pending: Mutex<HashMap<u64, oneshot::Sender<Reply>>>,
    next_id: AtomicU64,
    alive: AtomicBool,
}

fn core_path() -> Result<PathBuf, String> {
    let executable = std::env::current_exe().map_err(|_| "CORE_NOT_FOUND")?;
    let bundled = executable.parent().ok_or("CORE_NOT_FOUND")?.join("beeperlocal-core");
    if bundled.is_file() { return Ok(bundled); }
    if cfg!(debug_assertions) {
        let development = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("binaries/beeperlocal-core-aarch64-apple-darwin");
        if development.is_file() { return Ok(development); }
    }
    Err("CORE_NOT_FOUND".into())
}

impl Bridge {
    async fn launch(app: tauri::AppHandle) -> Result<Arc<Self>, String> {
        let mut child = Command::new(core_path()?)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
            .env_remove("PYTHONPATH").env_remove("PYTHONHOME")
            .env("PYTHONDONTWRITEBYTECODE", "1").env("PYTHONNOUSERSITE", "1")
            .kill_on_drop(true).spawn().map_err(|_| "CORE_START_FAILED")?;
        let input = child.stdin.take().ok_or("CORE_START_FAILED")?;
        let output = child.stdout.take().ok_or("CORE_START_FAILED")?;
        let bridge = Arc::new(Self { input: Mutex::new(Some(input)), child: Mutex::new(child),
            pending: Mutex::new(HashMap::new()), next_id: AtomicU64::new(1), alive: AtomicBool::new(true) });
        let reader_bridge = bridge.clone();
        tauri::async_runtime::spawn(async move {
            let mut reader = BufReader::new(output);
            let mut line = String::new();
            let mut fatal_error: Option<String> = None;
            loop {
                line.clear();
                match reader.read_line(&mut line).await {
                    Ok(0) | Err(_) => break,
                    Ok(_) if line.len() > 8 * 1024 * 1024 => break,
                    Ok(_) => {}
                }
                let value: Value = match serde_json::from_str(&line) { Ok(v) => v, Err(_) => break };
                if let Some(id) = value.get("id").and_then(Value::as_u64) {
                    if let Some(reply) = reader_bridge.pending.lock().await.remove(&id) {
                        let response = if value.get("ok").and_then(Value::as_bool) == Some(true) {
                            Ok(value.get("result").cloned().unwrap_or(Value::Null))
                        } else {
                            Err(value.get("error").and_then(Value::as_str).unwrap_or("CORE_ERROR").to_string())
                        };
                        let _ = reply.send(response);
                    }
                } else if value.get("event").is_some() {
                    if value.get("event").and_then(Value::as_str) == Some("fatal") {
                        fatal_error = value.get("error").and_then(Value::as_str).map(str::to_owned);
                    }
                    let _ = app.emit_to("main", "core-event", value);
                }
            }
            reader_bridge.alive.store(false, Ordering::SeqCst);
            let code = fatal_error.unwrap_or_else(|| "CORE_STOPPED".into());
            for (_, reply) in reader_bridge.pending.lock().await.drain() {
                let _ = reply.send(Err(code.clone()));
            }
            let _ = app.emit_to("main", "core-event", serde_json::json!({"event":"fatal","error":code}));
        });
        Ok(bridge)
    }

    async fn call(&self, request: CoreRequest) -> Reply {
        if !self.alive.load(Ordering::SeqCst) { return Err("CORE_STOPPED".into()); }
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let mut data = serde_json::to_vec(&serde_json::json!({"id":id,"request":request})).map_err(|_| "INVALID_INPUT")?;
        if data.len() > 96 * 1024 { return Err("INVALID_INPUT".into()); }
        data.push(b'\n');
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id, tx);
        let written = {
            let mut input = self.input.lock().await;
            match input.as_mut() {
                Some(stdin) => stdin.write_all(&data).await.is_ok(),
                None => false,
            }
        };
        if !written {
            self.pending.lock().await.remove(&id);
            return Err("CORE_STOPPED".into());
        }
        match tokio::time::timeout(Duration::from_secs(180), rx).await {
            Ok(Ok(reply)) => reply,
            _ => {
                self.pending.lock().await.remove(&id);
                Err("CORE_TIMEOUT".into())
            }
        }
    }

    async fn stop(&self) {
        self.input.lock().await.take(); // EOF lets Python close its own LINE child safely.
        let mut child = self.child.lock().await;
        if tokio::time::timeout(Duration::from_secs(15), child.wait()).await.is_err() {
            let _ = child.kill().await;
        }
    }
}

#[tauri::command]
async fn core_request(window: tauri::WebviewWindow, bridge: tauri::State<'_, Arc<Bridge>>, request: CoreRequest) -> Reply {
    if window.label() != "main" { return Err("INVALID_INPUT".into()); }
    bridge.call(request).await
}

fn main() {
    let application = tauri::Builder::default()
        .setup(|app| {
            let bridge = tauri::async_runtime::block_on(Bridge::launch(app.handle().clone()))
                .map_err(std::io::Error::other)?;
            app.manage(bridge);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![core_request])
        .build(tauri::generate_context!())
        .expect("BeeperLocal could not initialize");
    application.run(|app, event| {
        if let tauri::RunEvent::ExitRequested { .. } = event {
            if let Some(bridge) = app.try_state::<Arc<Bridge>>() {
                tauri::async_runtime::block_on(bridge.stop());
            }
        }
    });
}
