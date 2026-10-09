import { useEffect, useState } from 'react';
import { errorText, request } from './bridge';
import type { LoginState } from './types';

export function SlackLoginButton({ disabled, changed }: { disabled: boolean; changed: () => Promise<unknown> }) {
  const [state, setState] = useState<LoginState>({ stage: 'idle' });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [configured, setConfigured] = useState<boolean | null>(null);
  const active = state.stage === 'web';
  useEffect(() => {
    let disposed = false;
    void request<LoginState>({ provider: 'slack', op: 'slack_login_status' }).then(value => {
      if (!disposed) { setState(value); setConfigured(value.configured === true); }
    }).catch(cause => { if (!disposed) setError(errorText(cause)); });
    return () => { disposed = true; };
  }, []);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await request<LoginState>({ provider: 'slack', op: 'slack_login_status' });
        if (!disposed) {
          setState(value);
          if (value.stage === 'completed') await changed();
        }
      } catch (cause) { if (!disposed) setError(errorText(cause)); }
      if (!disposed) timer = setTimeout(poll, 700);
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [active]);
  async function act(cancel = false) {
    setWorking(true); setError('');
    try { setState(await request<LoginState>({ provider: 'slack', op: cancel ? 'slack_login_cancel' : 'slack_login_start' })); }
    catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  return <div className="setup-login">
    <button className="secondary" disabled={disabled || working || active || configured !== true} onClick={() => void act()}>Slackにログイン</button>
    <p className="settings-description">{configured === false ? 'このベータ版ではSlackの新規ログインをまだ利用できません。認証設定を含む更新版をお待ちください。すでに接続済みのアカウントは再接続できます。' : 'ブラウザでワークスペースを選び、メッセージの閲覧・送信を許可してください。'}</p>
    {active && <><p role="status">ブラウザでSlackの承認を待っています。</p><button className="secondary" disabled={working} onClick={() => void act(true)}>ログインを中止</button></>}
    {state.stage === 'completed' && <p role="status">Slackの認証を保存しました。再接続すると会話を読み込みます。</p>}
    {(error || state.errorCode) && <p className="settings-error" role="alert">{error || errorText(state.errorCode)}</p>}
  </div>;
}
