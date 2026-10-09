import { useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { isDemo } from './bridge';

const explanations: Record<string, string> = {
  UPDATE_NOT_CONFIGURED: '更新の配布先が未設定です。',
  UPDATE_CONFIG_INVALID: '更新設定を確認できません。',
  UPDATE_CHECK_FAILED: '更新を確認できません。後でもう一度お試しください。',
  UPDATE_VERIFY_FAILED: '更新ファイルの署名を確認できません。更新は適用されていません。',
  UPDATE_TOO_LARGE: '更新ファイルが上限を超えています。更新は適用されていません。',
  UPDATE_BUSY: '接続処理または送信が完了してから更新してください。',
  UPDATE_INSTALL_FAILED: '更新を適用できませんでした。各サービスへ再接続してください。',
};
export function UpdateButton({ blocked, busyChanged }: { blocked: boolean; busyChanged: (value: boolean) => void }) {
  const [version, setVersion] = useState('');
  const [message, setMessage] = useState('');
  const [working, setWorking] = useState(false);
  const lock = useRef(false);
  async function check(manual = false) {
    if (lock.current) return;
    lock.current = true; setWorking(true);
    try {
      const result = isDemo ? { available: false, version: '' } : await invoke<{ available: boolean; version?: string }>('check_update');
      setVersion(result.version ?? '');
      if (manual) setMessage(result.available ? '更新できます。適用後に再起動します。' : 'この配布先に新しい更新はありません。');
    } catch (e) { if (manual) setMessage(explanations[String(e)] ?? '更新を確認できませんでした。'); }
    finally { lock.current = false; setWorking(false); }
  }
  useEffect(() => {
    const timer = setTimeout(() => void check(), 10000);
    const interval = setInterval(() => void check(), 6 * 60 * 60 * 1000);
    return () => { clearTimeout(timer); clearInterval(interval); };
  }, []);
  async function install() {
    if (blocked || lock.current) return;
    lock.current = true; setWorking(true); busyChanged(true); setMessage('更新をダウンロードし、署名を確認しています。');
    try { await invoke('install_update'); }
    catch (e) { setVersion(''); setMessage(explanations[String(e)] ?? '更新を適用できませんでした。'); }
    finally { lock.current = false; setWorking(false); busyChanged(false); }
  }
  return <div className="update-control"><button className="settings-button" disabled={working} onClick={() => void check(true)}>更新を確認</button>{version && <><button className="secondary" disabled={blocked || working} onClick={() => void install()}>v{version}を適用して再起動</button>{blocked && <p>下書き・処理中の操作があるため更新を待機しています。</p>}</>}{message && <p role="status">{message}</p>}</div>;
}
