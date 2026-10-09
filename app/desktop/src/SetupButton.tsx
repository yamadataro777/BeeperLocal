import { useState } from 'react';
import { errorText, openSetup } from './bridge';
import { SlackLoginButton } from './SlackLoginButton';

export function SetupButton({ provider, disabled, changed }: { provider: 'instagram' | 'slack'; disabled: boolean; changed: () => Promise<unknown> }) {
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const name = provider === 'instagram' ? 'Instagram' : 'Slack';
  if (provider === 'slack') return <SlackLoginButton disabled={disabled} changed={changed}/>;
  async function open() {
    if (working) return;
    setWorking(true); setNotice(''); setError('');
    try {
      await openSetup(provider);
      setNotice('ターミナルとInstagram公式サイトの専用ログイン画面を開きました。本人確認を終えたら「ログイン完了・接続する」を押してください。ターミナルに「保存しました」と表示されたら、この画面で再接続してください。');
      await changed();
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  return <div className="setup-login">
    <button className="secondary" disabled={disabled || working} onClick={() => void open()}>{working ? 'ログイン画面を開いています…' : `${name}にログイン`}</button>
    <p className="settings-description">Instagram公式サイトの専用画面でログインと本人確認を進めます。通知が来ない場合は、公式画面に表示される別の確認方法を選んでください。</p>
    <p className="settings-description">鍵マークの「キーチェーン」確認に入力するのはMacのログインパスワードです。Instagramのパスワードとは別です。</p>
    {notice && <p className="settings-notice" role="status">{notice}</p>}
    {error && <p className="settings-error" role="alert">{error}</p>}
  </div>;
}
