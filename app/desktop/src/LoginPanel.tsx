import { useEffect, useRef, useState } from 'react';
import { request, errorText, isDemo } from './bridge';
import type { LoginState } from './types';

export function LoginPanel({ existing, close, completed }: { existing: boolean; close: () => void; completed: () => void }) {
  const [state, setState] = useState<LoginState>({ stage: 'idle' });
  const [working, setWorking] = useState(false);
  const [replace, setReplace] = useState(false);
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const active = !['idle', 'failed', 'cancelled', 'completed'].includes(state.stage);
  const replacing = existing || state.errorCode === 'LINE_LOGIN_REPLACEMENT_REQUIRED';
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const value = await request<LoginState>({ op: 'line_login_status' }); if (!disposed) setState(value); }
      catch (cause) { if (!disposed) setError(errorText(cause)); }
      if (!disposed) timer = setTimeout(poll, 700);
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [active]);
  async function start() {
    setWorking(true); setError('');
    try { setState(await request<LoginState>({ op: 'line_login_start', replace: replacing && replace })); }
    catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  async function dismiss() {
    if (working) return;
    setWorking(true);
    try {
      const value = await request<LoginState>({ op: 'line_login_cancel' });
      setState(value);
      if (value.stage === 'completed') completed(); else close();
    } catch (cause) { setError(errorText(cause)); setWorking(false); }
  }
  const status: Record<string, string> = {
    starting: 'QRコードを準備しています…', code: 'スマートフォンのLINEで読み取ってください',
    expired: '期限が切れました。新しいQRコードを準備しています…', scanned: 'スマートフォンでログインを承認してください',
    pin: 'この確認コードをスマートフォンのLINEに入力してください', phone_accepted: '承認を確認しています…',
    approved: '連携情報をこのMacに保存しています…', saving: '連携情報を確認しています…',
    completed: 'LINEの連携が完了しました', cancelled: '連携を中止しました',
  };
  const dimension = state.matrix?.length ?? 0;
  return <dialog ref={dialog} className="login-modal" aria-labelledby="login-title" onCancel={event => { event.preventDefault(); void dismiss(); }}>
    <div className="modal-heading"><h2 id="login-title">LINEを連携</h2><button className="icon-button" disabled={working} aria-label="連携画面を閉じる" onClick={() => void dismiss()}>×</button></div>
    {isDemo && <p className="settings-warning" role="note">画面確認用です。この画面のQRコードではLINEに連携できません。BeeperLocalアプリを開いてください。</p>}
    <p className="login-intro">スマートフォンのLINEアカウントを、このMacで使えるようにします。</p>
    {state.stage === 'code' && state.matrix && <div className="qr-frame"><svg role="img" aria-label="LINE連携用QRコード" viewBox={`0 0 ${dimension + 8} ${dimension + 8}`} shapeRendering="crispEdges"><rect width={dimension + 8} height={dimension + 8} fill="white"/><path fill="black" d={state.matrix.flatMap((row, y) => row.flatMap((on, x) => on ? [`M${x + 4},${y + 4}h1v1h-1z`] : [])).join('')}/></svg></div>}
    {state.stage === 'pin' && <div className="login-pin" aria-label="スマートフォンに入力する確認コード">{state.pin}</div>}
    {status[state.stage] && <p className="login-status" role="status">{active && state.stage !== 'code' && state.stage !== 'pin' && <span className="spinner"/>}{status[state.stage]}</p>}
    {active && <ol className="login-steps"><li>スマートフォンでLINEを開き、QRコードリーダーを開く</li><li>この画面のQRコードを読み取る</li><li>スマートフォンでログインを承認する。確認コードが表示されたら入力する</li></ol>}
    {(error || state.errorCode) && <p className="settings-error" role="alert">{error || errorText(state.errorCode)}</p>}
    {!active && state.stage !== 'completed' && <>
      <p className="settings-description">LINEのChrome版や同じ方式のクライアントが、ログアウトする場合があります。連携情報はMacのキーチェーンに保存します。</p>
      {replacing && <label className="check-row login-replace"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)}/>このMacに保存済みのLINEログインを更新する</label>}
      <button className="primary" disabled={working || (replacing && !replace)} onClick={() => void start()}>QRコードを表示して連携</button>
    </>}
    {active && <button className="secondary" disabled={working} onClick={() => void dismiss()}>連携を中止</button>}
    {state.stage === 'completed' && <button className="primary" onClick={completed}>会話一覧を開く</button>}
    <p className="login-note">QRコードと確認コードは、この画面でだけ使用します。画面を閉じると表示を消します。スマートフォンで承認済みのログインは、中止しても取り消せません。</p>
  </dialog>;
}
