import { useEffect, useRef, useState, type ReactNode } from 'react';
import { errorText, request as coreRequest } from './bridge';
import { StoragePanel } from './StoragePanel';
import { SetupButton } from './SetupButton';
import { APP_VERSION } from './version';
import type { ClientRegistration, Conversation, Management, Provider, Request } from './types';

type Props = { provider?: Provider; conversations: Conversation[]; connected: boolean; busy: boolean; close: () => void; connect: () => void; changed: () => Promise<unknown>; login: () => void; children?: ReactNode };
export function SettingsPanel({ provider = 'line', conversations, connected, busy, close, connect, changed, login, children }: Props) {
  const label = { line: 'LINE', slack: 'Slack', instagram: 'Instagram', x: 'X', messenger: 'Messenger' }[provider];
  const request = <T,>(value: Request) => coreRequest<T>({ ...value, provider });
  const [tab, setTab] = useState('line');
  const [data, setData] = useState<Management | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [port, setPort] = useState('28641');
  const [name, setName] = useState('');
  const [ids, setIds] = useState<string[]>([]);
  const [read, setRead] = useState(true);
  const [send, setSend] = useState(false);
  const [filter, setFilter] = useState('');
  const [registration, setRegistration] = useState<ClientRegistration | null>(null);
  const tokenCard = useRef<HTMLDivElement>(null);
  useEffect(() => { if (registration) tokenCard.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }, [registration]);
  useEffect(() => {
    let active = true;
    request<Management>({ op: 'management' }).then(value => { if (active) { setData(value); setPort(String(value.mcp.port)); } }).catch(cause => { if (active) setError(errorText(cause)); });
    return () => { active = false; };
  }, []);
  async function act(operation: Request, done?: (value: unknown) => void) {
    if (working) return;
    setWorking(true); setError('');
    try {
      const result = await request(operation);
      done?.(result);
      setData(await request<Management>({ op: 'management' }));
      await changed();
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  const disabled = busy || working;
  return <div className="settings-content">
    <div className="modal-heading"><h2 id="settings-title">{provider === 'line' || provider === 'slack' ? '接続設定' : `${label}接続`}</h2><button className="icon-button" aria-label="設定を閉じる" onClick={close} autoFocus>×</button></div>
    <div className="settings-tabs" role="tablist" aria-label="設定の種類">{[['line', `${label}接続`], ['mcp', 'MCP接続'], ['storage', '保存管理']].map(([id, title]) => <button role="tab" aria-selected={tab === id} key={id} onClick={() => setTab(id)}>{title}</button>)}</div>
    {error && <p className="settings-error" role="alert">{error}</p>}
    {tab === 'line' && provider === 'line' && <section aria-label="LINE接続">
      <div className="account-card"><span className="line-logo large">LINE</span><div><strong>このMacのLINEアカウント</strong><p>{connected ? '接続を確認済み' : '接続されていません'}</p></div></div>
      <p className="settings-description">取得済みの1対1会話を順番に同期し、新着を受信します。一時的な切断では再接続を試み、各会話の直近100件の範囲を補います。</p>
      <div className="settings-actions"><button className="primary" disabled={disabled || data?.storage.paused} onClick={() => { close(); connect(); }}>再接続・一覧更新</button><button className="secondary" disabled={disabled || !connected} onClick={() => void act({ op: 'stop' }, close)}>受信を停止</button></div>
      <button className="secondary line-login-button" disabled={disabled || data?.storage.paused} onClick={login}>QRコードでLINEを連携・再ログイン</button>
      {data?.storage.paused && <p className="settings-description">保存を停止中です。「保存管理」で再開できます。</p>}
      <hr/><p className="settings-description">停止中の100件を超える受信、過去の全履歴、削除・送信取消の完全な同期には対応していません。再接続が続けて失敗した場合は手動で再接続してください。</p>
    </section>}
    {tab === 'line' && provider === 'slack' && <section aria-label="Slack接続"><h3>このMacのSlackアカウント</h3><p className="settings-description">保存済みのUser OAuth認証を使います。本人が参加するDM・グループDM・チャンネルを選択し、本人名義でテキストを送信します。Botへの接続ではありません。</p><p className="settings-description">会話と発見済みのスレッドを約65秒に1ページずつ巡回します。会話数が増えると巡回に時間がかかります。過去履歴の追加取得と、閲覧権限を付けたMCPからのスレッド取得にも対応します。</p><p className="settings-description">初回認証・期限切れ時は「Slackにログイン」から本人認証してください。送信にはUser権限の追加承認が必要です。現在は1ワークスペースのみ接続できます。</p><p className="settings-description">名前とプロフィール画像の表示にはSlack側でプロフィール閲覧の許可が必要です。許可を追加した後は「再接続・一覧更新」を押してください。画像が取得できなくても会話の読み書きは続けられます。</p><div className="settings-actions"><button className="primary" disabled={disabled || data?.storage.paused} onClick={() => { close(); connect(); }}>再接続・一覧更新</button><button className="secondary" disabled={disabled || !connected} onClick={() => void act({ op: 'stop' }, close)}>定期取得を停止</button></div><SetupButton provider="slack" disabled={disabled || !!data?.storage.paused} changed={async () => { setData(await request<Management>({ op: 'management' })); await changed(); }}/></section>}
    {tab === 'mcp' && <section aria-label="MCP接続">
      <p className="settings-description">このMacのAIクライアントへ、{label}の選んだ会話だけを許可できます。閲覧・検索と送信の権限は別に設定します。他サービスには適用されず、アプリを終了すると接続も停止します。</p>
      <div className="settings-card"><strong>{data?.mcp.running ? 'MCP 接続受付中' : 'MCP 停止中'}</strong><label className="field">ポート番号<input type="number" min="1024" max="65535" value={port} onChange={e => setPort(e.target.value)}/></label><div className="settings-actions"><button className="primary" disabled={disabled || !data || !Number.isInteger(Number(port)) || Number(port) < 1024 || Number(port) > 65535} onClick={() => void act({ op: 'mcp_configure', enabled: true, port: Number(port) })}>{data?.mcp.running ? 'ポートを適用' : 'MCPを有効にする'}</button><button className="secondary" disabled={disabled || !data?.mcp.enabled} onClick={() => void act({ op: 'mcp_configure', enabled: false, port: Number(data!.mcp.port) })}>MCPを停止</button></div>{data?.mcp.errorCode && <p role="alert">{errorText(data.mcp.errorCode)}</p>}<label className="field">接続先URL<input readOnly value={data?.mcp.url ?? ''}/></label></div>
      <div className="settings-card"><h3>クライアントを登録</h3><label className="field">クライアント名<input value={name} maxLength={80} placeholder="例：手元のAIアシスタント" onChange={e => setName(e.target.value)}/></label><label className="field">許可する会話を探す<input value={filter} onChange={e => setFilter(e.target.value)} placeholder="会話の名前"/></label><div className="scope-list" aria-label="許可する会話">{conversations.filter(c => c.title.toLocaleLowerCase().includes(filter.toLocaleLowerCase())).map(c => <label className="check-row" key={c.id}><input type="checkbox" checked={ids.includes(c.id)} onChange={e => setIds(values => e.target.checked ? [...values, c.id] : values.filter(id => id !== c.id))}/><span>{c.title}</span></label>)}</div><p className="settings-description">{ids.length}件を選択。選んでいない会話にはアクセスできません。</p><label className="check-row"><input type="checkbox" checked={read} onChange={e => setRead(e.target.checked)}/>{provider === 'slack' ? '保存済みメッセージの閲覧・検索とスレッド取得を許可' : '保存済みメッセージの閲覧・検索を許可'}</label><label className="check-row"><input type="checkbox" checked={send} onChange={e => setSend(e.target.checked)}/>選んだ会話への送信を許可</label>{send && <p className="settings-warning">このクライアントは、送信のたびにアプリで確認せずメッセージを送れます。</p>}<p className="settings-description">AI側に渡した内容は、そのサービスでも処理・保存される場合があります。権限の取り消しやローカル削除では、渡した内容を回収できません。</p><button className="primary" disabled={disabled || !data?.accountAvailable || !name.trim() || !ids.length || (!read && !send)} onClick={() => void act({ op: 'mcp_register', name, conversationIds: ids, read, send }, value => { setRegistration(value as ClientRegistration); setName(''); setIds([]); setRead(true); setSend(false); })}>この権限で登録</button></div>
      {registration && <div ref={tokenCard} className="settings-card token-card" role="region" aria-label="新しい接続トークン"><h3>接続トークン</h3><p className="settings-description">表示は今回だけです。閉じる前にクライアントへ設定してください。トークンを持つアプリは、この権限を使えます。</p><label className="field">トークン<input readOnly value={registration.token} onFocus={e => e.target.select()}/></label><p className="settings-description">接続方式：Streamable HTTP<br/>URL：{registration.url}<br/>認証ヘッダー：Authorization: Bearer トークン</p><button className="secondary" onClick={() => setRegistration(null)}>トークンを隠す</button></div>}
      <h3>登録済みクライアント</h3>{!data?.clients.length && <p className="settings-description">まだ登録されていません。</p>}{data?.clients.map(client => <div className="client-row" key={client.id}><div><strong>{client.name}</strong><p>{client.conversationIds.length}会話 · {client.read ? '閲覧・検索' : ''}{client.read && client.send ? ' / ' : ''}{client.send ? '送信' : ''}</p><details><summary>許可した会話</summary>{client.conversationIds.map(id => <p key={id}>{conversations.find(c => c.id === id)?.title ?? '保存済みの会話'}</p>)}</details></div><button className="secondary" disabled={disabled} aria-label={`${client.name}の権限を取り消す`} onClick={() => void act({ op: 'mcp_revoke', clientId: client.id }, () => { if (registration?.client.id === client.id) setRegistration(null); })}>取り消す</button></div>)}
    </section>}
    {tab === 'line' && children}
    {tab === 'storage' && <StoragePanel provider={provider} busy={disabled} changed={changed}/>}
    <p className="version">BeeperLocal {APP_VERSION} · ベータ候補版</p>
  </div>;
}
