import { useEffect, useRef, useState } from 'react';
import { errorText, isDemo, request } from './bridge';
import type { LoginState } from './types';

export function MessengerLoginPanel({ close, completed }: { close: () => void; completed: () => void }) {
  const [state, setState] = useState<LoginState>({ stage: 'idle' });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const active = state.stage === 'web' || state.stage === 'starting';
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await request<LoginState>({ provider: 'messenger', op: 'messenger_login_status' });
        if (!disposed) setState(value);
      } catch (cause) { if (!disposed) setError(errorText(cause)); }
      if (!disposed) timer = setTimeout(poll, 700);
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [active]);
  async function start() {
    setWorking(true); setError('');
    try { setState(await request<LoginState>({ provider: 'messenger', op: 'messenger_login_start' })); }
    catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  async function dismiss() {
    if (working) return;
    setWorking(true);
    try {
      const value = await request<LoginState>({ provider: 'messenger', op: 'messenger_login_cancel' });
      if (value.stage === 'completed') completed(); else close();
    } catch (cause) { setError(errorText(cause)); setWorking(false); }
  }
  return <dialog ref={dialog} className="login-modal" aria-labelledby="messenger-login-title" onCancel={event => { event.preventDefault(); void dismiss(); }}>
    <div className="modal-heading"><h2 id="messenger-login-title">Messengerを連携</h2><button className="icon-button" disabled={working} aria-label="Messenger連携画面を閉じる" onClick={() => void dismiss()}>×</button></div>
    {isDemo && <p className="settings-warning">画面確認用です。実際の認証は行いません。</p>}
    <p className="login-intro">専用ウィンドウでFacebookに本人ログインし、「ログイン完了・接続する」を押してください。</p>
    <p className="settings-description">初回接続時はMessengerの暗号化端末として登録します。保存済みの端末がある場合はその鍵を引き継ぎます。再ログインには同じアカウントを使ってください。</p>
    {active && <p className="login-status" role="status"><span className="spinner"/>別ウィンドウでFacebookにログインしてください。</p>}
    {(error || state.errorCode) && <p className="settings-error" role="alert">{error || errorText(state.errorCode)}</p>}
    {!active && state.stage !== 'completed' && <button className="primary" disabled={working} onClick={() => void start()}>Facebookのログイン画面を開く</button>}
    {active && <button className="secondary" disabled={working} onClick={() => void dismiss()}>連携を中止</button>}
    {state.stage === 'completed' && <><p role="status">ログインを保存しました</p><button className="primary" onClick={completed}>会話一覧を開く</button></>}
    <p className="login-note">受信とローカル検索に対応しています。過去の暗号化バックアップの復元は未対応です。</p>
  </dialog>;
}

export function MessengerSettingsPanel({ busy, connected, paused, connect, login, stop }: {
  busy: boolean; connected: boolean; paused: boolean; connect: () => void;
  login: () => void; stop: () => void;
}) {
  return <section aria-label="Messenger接続">
    <p className="settings-description">この端末へ届く1対1の暗号化テキストを受信し、このMacに保存・検索し、テキストを送信できます。会話を切り替えても受信は続きます。</p>
    <p className="settings-description">保存済みの履歴を表示します。過去の暗号化バックアップ・全会話一覧・グループ・添付・消えるメッセージには未対応です。外部AIへの会話の許可は「MCP接続」で設定できます。</p>
    <div className="settings-actions">
      <button className="primary" disabled={busy || paused} onClick={connect}>再接続・一覧更新</button>
      <button className="secondary" disabled={busy || paused} onClick={login}>Facebookにログイン</button>
      <button className="secondary" disabled={busy || !connected} onClick={stop}>受信を停止</button>
    </div>
    <p className="settings-description">端末鍵とログインはキーチェーン、受信本文は専用の暗号化保存領域で保護します。端末の削除・再登録は自動で行いません。</p>
  </section>;
}
