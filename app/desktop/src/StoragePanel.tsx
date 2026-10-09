import { useEffect, useState } from 'react';
import { errorText, request } from './bridge';
import type { DeletionPreview, Management, Provider, Request } from './types';

export function StoragePanel({ provider, busy, changed }: { provider: Provider; busy: boolean; changed: () => Promise<unknown> }) {
  const [data, setData] = useState<Management | null>(null);
  const [preview, setPreview] = useState<DeletionPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const label = { line: 'LINE', slack: 'Slack', instagram: 'Instagram', x: 'X', messenger: 'Messenger' }[provider];
  const load = () => request<Management>({ provider, op: 'management' });
  useEffect(() => {
    let active = true;
    void load().then(value => { if (active) setData(value); }).catch(cause => { if (active) setError(errorText(cause)); });
    return () => { active = false; };
  }, [provider]);
  async function act(value: Request) {
    if (working) return;
    setWorking(true); setError(''); setNotice('');
    try {
      const result = await request<DeletionPreview>({ ...value, provider });
      setPreview(value.op === 'storage_delete_preview' ? result : null); setConfirmed(false);
      if (value.op === 'storage_delete') setNotice('対象データを削除しました。保存は停止中です。');
      if (value.op === 'storage_pause' && !value.paused) setNotice('保存を再開しました。接続設定から再接続してください。');
      setData(await load()); await changed();
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  const disabled = busy || working || !data;
  return <section aria-label="保存管理">
    <h3>{label}の保存管理</h3>
    {error && <p className="settings-error" role="alert">{error}</p>}
    {notice && <p className="settings-notice" role="status">{notice}</p>}
    <p className="settings-description">このMacに暗号化して保存します。保存停止中は受信・履歴取得・送信が止まり、保存済みの内容は閲覧できます。</p>
    <div className="settings-card"><strong>{data?.storage.paused ? '保存停止中' : '保存中'}</strong>
      <p>現在の{label}：{data?.storage.counts.messages ?? 0}メッセージ / {data?.storage.counts.conversations ?? 0}会話</p>
      <button className="secondary" disabled={disabled} onClick={() => void act({ op: 'storage_pause', paused: !data!.storage.paused })}>{data?.storage.paused ? '保存を再開' : '保存を停止'}</button>
      <details><summary>保存場所</summary><p className="storage-path">{data?.storage.path}</p></details>
    </div>
    <div className="settings-card"><h3>この{label}アカウントの保存データを削除</h3>
      <p className="settings-description">会話・メッセージ・取得履歴・送信記録と、このアカウントのMCP権限を削除します。ログイン情報・暗号鍵・他のサービスのデータは保持します。サービス側のメッセージは削除されません。</p>
      <p className="settings-description">対象を確認すると保存が停止し、削除後も停止が続きます。再接続すると履歴が再び保存されます。二重送信を防ぐため送信要求の識別用ハッシュは保持します。</p>
      <button className="secondary" disabled={disabled || !data?.accountAvailable} onClick={() => void act({ op: 'storage_delete_preview' })}>削除対象を確認</button>
      {preview && <div className="delete-confirm"><p>{preview.counts.messages ?? 0}メッセージ、{preview.counts.conversations ?? 0}会話、{preview.counts.outgoing_requests ?? 0}送信記録が対象です。</p>
        <label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>このMacの対象データを削除することを確認しました</label>
        <p className="settings-description">確認の有効期限は2分です。</p>
        <button className="danger" disabled={disabled || !confirmed} onClick={() => void act({ op: 'storage_delete', confirmation: preview.confirmation })}>確認したデータを削除</button>
      </div>}
    </div>
  </section>;
}
