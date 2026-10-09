use crate::{Bridge, CoreRequest};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{sync::{Arc, atomic::Ordering}, time::Duration};
use tauri::{Emitter, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};
use tokio::sync::Mutex;

#[derive(Default)]
pub struct Updates(pub Mutex<Option<Update>>);

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Channel { endpoint: String, public_key: String }

fn channel() -> Result<Channel, String> {
    let c: Channel = serde_json::from_str(include_str!("../update-channel.json")).map_err(|_| "UPDATE_CONFIG_INVALID")?;
    if c.endpoint.is_empty() || c.public_key.is_empty() { return Err("UPDATE_NOT_CONFIGURED".into()); }
    if !c.endpoint.starts_with("https://") { return Err("UPDATE_CONFIG_INVALID".into()); }
    Ok(c)
}

#[tauri::command]
pub async fn check_update(window: tauri::WebviewWindow, updates: tauri::State<'_, Updates>) -> Result<Value, String> {
    if window.label() != "main" { return Err("INVALID_INPUT".into()); }
    let c = channel()?;
    let mut cached = updates.0.try_lock().map_err(|_| "UPDATE_BUSY")?;
    let endpoint = c.endpoint.parse().map_err(|_| "UPDATE_CONFIG_INVALID")?;
    let result = window.app_handle().updater_builder().pubkey(c.public_key)
        .endpoints(vec![endpoint]).map_err(|_| "UPDATE_CONFIG_INVALID")?
        .timeout(Duration::from_secs(300)).no_proxy()
        .configure_client(|client| client.https_only(true))
        .build().map_err(|_| "UPDATE_CONFIG_INVALID")?
        .check().await.map_err(|_| "UPDATE_CHECK_FAILED")?;
    if let Some(ref update) = result {
        if update.download_url.scheme() != "https" || !update.download_url.username().is_empty() || update.download_url.password().is_some() {
            return Err("UPDATE_CONFIG_INVALID".into());
        }
    }
    let view = result.as_ref().map(|u| json!({"available":true,"version":u.version})).unwrap_or(json!({"available":false}));
    *cached = result;
    Ok(view)
}

#[tauri::command]
pub async fn install_update(window: tauri::WebviewWindow, updates: tauri::State<'_, Updates>, bridge: tauri::State<'_, Arc<Bridge>>) -> Result<(), String> {
    if window.label() != "main" { return Err("INVALID_INPUT".into()); }
    let mut cached = updates.0.try_lock().map_err(|_| "UPDATE_BUSY")?;
    let update = cached.take().ok_or("UPDATE_CHECK_REQUIRED")?;
    // Download and verify the artifact plus signed version BEFORE stopping any service.
    let too_large = tokio::sync::Notify::new();
    let mut received: u64 = 0;
    let bytes = tokio::select! {
        result = update.download(|chunk, total| {
            received = received.saturating_add(chunk as u64);
            if received > 512 * 1024 * 1024 || total.is_some_and(|n| n > 512 * 1024 * 1024) { too_large.notify_one(); }
            let _ = window.emit("update-progress", json!({"received":received,"total":total}));
        }, || {}) => result.map_err(|_| "UPDATE_VERIFY_FAILED")?,
        _ = too_large.notified() => return Err("UPDATE_TOO_LARGE".into()),
    };
    if bytes.len() > 512 * 1024 * 1024 { return Err("UPDATE_TOO_LARGE".into()); }
    if bridge.maintenance.swap(true, Ordering::SeqCst) { return Err("UPDATE_BUSY".into()); }
    // The writer checks the same gate. An in-flight mutation must finish first.
    let _writer = bridge.input.lock().await;
    if !bridge.replies.lock().await.pending.is_empty() {
        bridge.maintenance.store(false, Ordering::SeqCst);
        return Err("UPDATE_BUSY".into());
    }
    drop(_writer);
    if bridge.call(CoreRequest::PrepareUpdate {}).await.is_err() {
        bridge.maintenance.store(false, Ordering::SeqCst);
        return Err("UPDATE_BUSY".into());
    }
    // Python stopped all receivers and MCP servers while holding each send lock.
    let result = update.install(&bytes).map_err(|_| "UPDATE_INSTALL_FAILED".to_string());
    if result.is_ok() {
        bridge.stop().await;
        window.app_handle().restart();
    }
    bridge.maintenance.store(false, Ordering::SeqCst);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn release_signer_is_compatible_with_updater_verifier_and_rejects_tampering() {
        let fixture: Value = serde_json::from_str(include_str!("../../../tests/fixtures/update-signature.json")).unwrap();
        let key = minisign_verify::PublicKey::decode(fixture["publicKey"].as_str().unwrap()).unwrap();
        let signature = minisign_verify::Signature::decode(fixture["signature"].as_str().unwrap()).unwrap();
        assert!(key.verify(fixture["body"].as_str().unwrap().as_bytes(), &signature, false).is_ok());
        assert!(key.verify(b"modified archive", &signature, false).is_err());
        assert!(signature.trusted_comment().split('\t').any(|f| f == "version:0.0.2"));
        let changed = fixture["signature"].as_str().unwrap().replace("version:0.0.2", "version:9.9.9");
        let changed = minisign_verify::Signature::decode(&changed).unwrap();
        assert!(key.verify(fixture["body"].as_str().unwrap().as_bytes(), &changed, false).is_err());
    }
}
