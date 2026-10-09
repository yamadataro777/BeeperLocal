#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod updates;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashMap, path::PathBuf, process::Stdio, sync::{Arc, atomic::{AtomicBool, AtomicU64, Ordering}}, time::Duration};
use tauri::{Emitter, Manager};
use tokio::{io::{AsyncBufReadExt, AsyncWriteExt, BufReader}, process::{Child, ChildStdin, Command}, sync::{Mutex, oneshot}};

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum Provider { Line, Instagram, Slack, X, Messenger }

// LINE-only commands accept the same explicit scope as the React bridge, but
// cannot be routed to another provider. Keep omitted scope for older callers.
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum LineProvider { Line }

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum AvatarProvider { Line, Instagram }

#[derive(Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case", rename_all_fields = "camelCase", deny_unknown_fields)]
enum CoreRequest {
    PrepareUpdate {},
    Snapshot { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    LineLoginStart { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<LineProvider>, replace: bool },
    LineLoginStatus { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<LineProvider> },
    LineLoginCancel { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<LineProvider> },
    MessengerLoginStart { provider: Provider },
    MessengerLoginStatus { provider: Provider },
    MessengerLoginCancel { provider: Provider },
    SlackLoginStart { provider: Provider },
    SlackLoginStatus { provider: Provider },
    SlackLoginCancel { provider: Provider },
    XLoginStart { provider: Provider, unlock_only: bool },
    XLoginStatus { provider: Provider },
    XLoginCancel { provider: Provider },
    Avatar { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<AvatarProvider>, conversation_id: String },
    LineMedia { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<LineProvider>, conversation_id: String, message_id: String, retry: bool },
    AttachmentMedia { provider: Provider, conversation_id: String, message_id: String, index: u8, retry: bool },
    SlackProfile { provider: Provider, conversation_id: String, #[serde(skip_serializing_if = "Option::is_none")] message_id: Option<String> },
    Connect { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, #[serde(skip_serializing_if = "Option::is_none")] interactive: Option<bool> },
    Select { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String },
    Messages { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String },
    MessagesOlder { provider: Provider, conversation_id: String, before: String },
    MarkRead { provider: Provider, conversation_id: String, through_message_id: String },
    HistoryBackfill { provider: Provider, conversation_id: Option<String>, enabled: bool },
    Refresh { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    Stop { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    Search { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, query: String },
    Send { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String, text: String, request_id: String },
    SendImage { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, conversation_id: String, data_url: String, request_id: String },
    Management { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    McpConfigure { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, enabled: bool, port: u16 },
    McpRegister { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, name: String, conversation_ids: Vec<String>, read: bool, send: bool },
    McpRevoke { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, client_id: String },
    StoragePause { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, paused: bool },
    StorageDeletePreview { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider> },
    StorageDelete { #[serde(skip_serializing_if = "Option::is_none")] provider: Option<Provider>, confirmation: String },
}

type Reply = Result<Value, String>;

#[derive(Default)]
struct ReplyState {
    pending: HashMap<u64, oneshot::Sender<Reply>>,
    stopped: Option<String>,
}

impl ReplyState {
    fn register(&mut self, id: u64, reply: oneshot::Sender<Reply>) -> Result<(), String> {
        if let Some(code) = &self.stopped { return Err(code.clone()); }
        self.pending.insert(id, reply);
        Ok(())
    }

    fn stop(&mut self, code: String) {
        let code = self.stopped.get_or_insert(code).clone();
        for (_, reply) in self.pending.drain() { let _ = reply.send(Err(code.clone())); }
    }
}

struct Bridge {
    input: Mutex<Option<ChildStdin>>,
    child: Mutex<Child>,
    replies: Mutex<ReplyState>,
    next_id: AtomicU64,
    maintenance: AtomicBool,
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
            replies: Mutex::new(ReplyState::default()), next_id: AtomicU64::new(1), maintenance: AtomicBool::new(false) });
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
                    if let Some(reply) = reader_bridge.replies.lock().await.pending.remove(&id) {
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
            let code = fatal_error.unwrap_or_else(|| "CORE_STOPPED".into());
            reader_bridge.replies.lock().await.stop(code.clone());
            let _ = app.emit_to("main", "core-event", serde_json::json!({"event":"fatal","error":code}));
        });
        Ok(bridge)
    }

    async fn call(&self, request: CoreRequest) -> Reply {
        let preparing_update = matches!(request, CoreRequest::PrepareUpdate {});
        if self.maintenance.load(Ordering::SeqCst) && !preparing_update { return Err("UPDATE_BUSY".into()); }
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let mut data = serde_json::to_vec(&serde_json::json!({"id":id,"request":request})).map_err(|_| "INVALID_INPUT")?;
        let maximum = if matches!(request, CoreRequest::SendImage { .. }) { 6 * 1024 * 1024 } else { 96 * 1024 };
        if data.len() > maximum { return Err("INVALID_INPUT".into()); }
        data.push(b'\n');
        let (tx, rx) = oneshot::channel();
        // Registration and termination share a lock. A Core that exits before
        // the WebView subscribes must still explain its original startup error.
        self.replies.lock().await.register(id, tx)?;
        let written = {
            let mut input = self.input.lock().await;
            if self.maintenance.load(Ordering::SeqCst) && !preparing_update {
                self.replies.lock().await.pending.remove(&id);
                return Err("UPDATE_BUSY".into());
            }
            match input.as_mut() {
                Some(stdin) => stdin.write_all(&data).await.is_ok(),
                None => false,
            }
        };
        if !written {
            let mut replies = self.replies.lock().await;
            replies.pending.remove(&id);
            return Err(replies.stopped.clone().unwrap_or_else(|| "CORE_STOPPED".into()));
        }
        match tokio::time::timeout(Duration::from_secs(180), rx).await {
            Ok(Ok(reply)) => reply,
            _ => {
                self.replies.lock().await.pending.remove(&id);
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

#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum SetupProvider { Instagram, Slack }

#[tauri::command]
async fn open_setup(window: tauri::WebviewWindow, provider: SetupProvider) -> Result<(), String> {
    if window.label() != "main" { return Err("INVALID_INPUT".into()); }
    let name = match provider {
        SetupProvider::Instagram => "Instagram接続.command",
        SetupProvider::Slack => "Slack接続.command",
    };
    let path = window.app_handle().path().resource_dir()
        .map_err(|_| "SETUP_OPEN_FAILED")?.join("resources").join(name);
    if !path.is_file() || path.is_symlink() { return Err("SETUP_OPEN_FAILED".into()); }
    // Fixed executable, fixed bundled scripts, separate argv. No supplied URL,
    // shell expression, token or arbitrary path crosses this command boundary.
    let status = Command::new("/usr/bin/open").args(["-a", "Terminal"]).arg(path)
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
        .status().await.map_err(|_| "SETUP_OPEN_FAILED")?;
    if status.success() { Ok(()) } else { Err("SETUP_OPEN_FAILED".into()) }
}

fn main() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(updates::Updates::default())
        .setup(|app| {
            let bridge = tauri::async_runtime::block_on(Bridge::launch(app.handle().clone()))
                .map_err(std::io::Error::other)?;
            app.manage(bridge);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![core_request, open_setup, updates::check_update, updates::install_update])
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn startup_failure_reaches_pending_and_late_webview_requests() {
        let mut state = ReplyState::default();
        let (tx, mut rx) = oneshot::channel();
        state.register(1, tx).unwrap();
        state.stop("DESKTOP_ALREADY_RUNNING".into());
        assert_eq!(rx.try_recv().unwrap(), Err("DESKTOP_ALREADY_RUNNING".into()));
        assert!(state.pending.is_empty());
        let (late, _) = oneshot::channel();
        assert_eq!(state.register(2, late), Err("DESKTOP_ALREADY_RUNNING".into()));
        state.stop("CORE_STOPPED".into());
        assert_eq!(state.stopped.as_deref(), Some("DESKTOP_ALREADY_RUNNING"));
    }

    #[test]
    fn line_commands_accept_actual_frontend_scope_and_preserve_legacy_callers() {
        let requests = [
            json!({"op":"line_login_start","replace":false}),
            json!({"op":"line_login_status"}), json!({"op":"line_login_cancel"}),
            json!({"op":"line_media","conversationId":"fixture","messageId":"fixture","retry":false}),
        ];
        for request in requests {
            assert!(serde_json::from_value::<CoreRequest>(request.clone()).is_ok());
            let mut scoped = request.clone();
            scoped["provider"] = json!("line");
            let parsed: CoreRequest = serde_json::from_value(scoped.clone()).unwrap();
            assert_eq!(serde_json::to_value(parsed).unwrap(), scoped);
            for provider in ["slack", "instagram", "x", "messenger"] {
                scoped["provider"] = json!(provider);
                assert!(serde_json::from_value::<CoreRequest>(scoped.clone()).is_err());
            }
            let mut extra = request;
            extra["path"] = json!("/tmp/fixture");
            assert!(serde_json::from_value::<CoreRequest>(extra).is_err());
        }
    }

    #[test]
    fn provider_operations_keep_explicit_scope() {
        for provider in ["line", "instagram", "slack", "x", "messenger"] {
            for request in [
                json!({"op":"storage_delete_preview", "provider":provider}),
                json!({"op":"storage_delete", "provider":provider,"confirmation":"fixture"}),
                json!({"op":"snapshot", "provider":provider}),
                json!({"op":"mcp_configure", "provider":provider,"enabled":true,"port":28644}),
                json!({"op":"mcp_register", "provider":provider,"name":"fixture","conversationIds":["fixture"],"read":true,"send":false}),
                json!({"op":"mcp_revoke", "provider":provider,"clientId":"fixture"}),
                json!({"op":"storage_pause", "provider":provider, "paused":true}),
                json!({"op":"search", "provider":provider, "query":"fixture"}),
                json!({"op":"send", "provider":provider,"conversationId":"fixture","text":"fixture","requestId":"fixture"}),
                json!({"op":"send_image", "provider":provider,"conversationId":"fixture","dataUrl":"data:image/png;base64,fixture","requestId":"fixture"}),
                json!({"op":"connect", "provider":provider,"interactive":true}),
            ] {
                let parsed: CoreRequest = serde_json::from_value(request.clone()).unwrap();
                assert_eq!(serde_json::to_value(parsed).unwrap(), request);
            }
        }
    }

    #[test]
    fn avatars_accept_line_and_instagram_but_never_arbitrary_urls() {
        for provider in ["line", "instagram"] {
            let request = json!({"op":"avatar","provider":provider,"conversationId":"fixture"});
            let parsed: CoreRequest = serde_json::from_value(request.clone()).unwrap();
            assert_eq!(serde_json::to_value(parsed).unwrap(), request);
            let mut invalid = request; invalid["url"] = json!("https://untrusted.invalid/photo");
            assert!(serde_json::from_value::<CoreRequest>(invalid).is_err());
        }
        for provider in ["slack", "x", "messenger"] {
            assert!(serde_json::from_value::<CoreRequest>(json!({"op":"avatar","provider":provider,"conversationId":"fixture"})).is_err());
        }
    }

    #[test]
    fn setup_cannot_launch_an_arbitrary_target() {
        for value in ["line", "file:///tmp/test", "https://example.test", "../test", "/bin/sh"] {
            assert!(serde_json::from_value::<SetupProvider>(json!(value)).is_err());
        }
        assert!(serde_json::from_value::<SetupProvider>(json!("instagram")).is_ok());
        assert!(serde_json::from_value::<SetupProvider>(json!("slack")).is_ok());
    }
}
