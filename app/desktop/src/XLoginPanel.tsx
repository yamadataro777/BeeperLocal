import { useEffect, useRef, useState } from 'react';
import { request, errorText, isDemo } from './bridge';
import type { LoginState } from './types';

export function XLoginPanel({ unlockOnly, close, completed }: { unlockOnly: boolean; close: () => void; completed: () => void }) {
  const [state, setState] = useState<LoginState>({ stage: 'idle' });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const active = ['starting', 'web', 'pin'].includes(state.stage);
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const value = await request<LoginState>({ provider: 'x', op: 'x_login_status' }); if (!disposed) setState(value); }
      catch (cause) { if (!disposed) setError(errorText(cause)); }
      if (!disposed) timer = setTimeout(poll, 700);
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [active]);
  async function start() {
    setWorking(true); setError('');
    try { setState(await request<LoginState>({ provider: 'x', op: 'x_login_start', unlockOnly })); }
    catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  async function dismiss() {
    if (working) return;
    setWorking(true);
    try {
      const value = await request<LoginState>({ provider: 'x', op: 'x_login_cancel' });
      if (value.stage === 'completed') completed(); else close();
    } catch (cause) { setError(errorText(cause)); setWorking(false); }
  }
  const labels: Record<string, string> = { starting: '接続画面を準備しています…', web: '別ウィンドウでXにログインしてください。', pin: '別ウィンドウでChatパスコードを入力してください。', completed: 'Xの連携が完了しました', cancelled: '連携を中止しました' };
  return <dialog ref={dialog} className="login-modal" aria-labelledby="x-login-title" onCancel={event => { event.preventDefault(); void dismiss(); }}>
    <div className="modal-heading"><h2 id="x-login-title">𝕏を連携</h2><button className="icon-button" disabled={working} aria-label="X連携画面を閉じる" onClick={() => void dismiss()}>×</button></div>
    {isDemo && <p className="settings-warning">画面確認用です。実際の認証は行いません。</p>}
    <p className="login-intro">{unlockOnly ? '保存済みのログインで、X Chatの暗号鍵を解除します。' : '専用ウィンドウでXにログインし、右上の「ログイン完了・接続する」を押してください。'}</p>
    <p className="settings-description">Chatパスコードが必要な場合は、続いてMacの入力画面が開きます。確認は1回だけ行い、パスワードやパスコード自体は保存しません。</p>
    {labels[state.stage] && <p className="login-status" role="status">{active && <span className="spinner"/>}{labels[state.stage]}</p>}
    {(error || state.errorCode) && <p className="settings-error" role="alert">{error || errorText(state.errorCode)}</p>}
    {!active && state.stage !== 'completed' && <button className="primary" disabled={working} onClick={() => void start()}>{unlockOnly ? 'Chatパスコードを入力する' : 'Xのログイン画面を開く'}</button>}
    {active && <button className="secondary" disabled={working} onClick={() => void dismiss()}>連携を中止</button>}
    {state.stage === 'completed' && <button className="primary" onClick={completed}>会話一覧を開く</button>}
    <p className="login-note">保存済みのログインがある場合は、同じXアカウントだけを利用できます。</p>
  </dialog>;
}
