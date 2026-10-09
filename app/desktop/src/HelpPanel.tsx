import { useState } from 'react';
import type { Provider, Snapshot } from './types';
import { APP_VERSION } from './version';

const services = [
  ['LINE', 'スマートフォンでQRコードを読み取って連携', '1対1の送受信、画像・静止画スタンプ、保存・検索。サービス側の履歴取得は直近の範囲です。本家Beeper・Chrome版LINEとの同一アカウントの同時利用はできません。切断時は再ログインが必要と表示します。'],
  ['Instagram', '接続設定の「Instagramにログイン」から連携', 'DM・参加済みグループのテキスト送受信、添付の表示、過去履歴の追加取得。公式サイトの専用画面で本人確認を進めます。通知が届かない場合は、画面に表示される別の確認方法を選んでください。'],
  ['Slack', 'ブラウザでワークスペースを選んで承認', 'DM・グループDM・参加チャンネルとスレッドを順番に取得。取得は約65秒ごとに1ページです。保存期間と権限による制限があります。1ワークスペースのみ。'],
  ['𝕏', '接続設定から本人ログインし、Chatパスコードで解除', 'DM・参加済みグループのテキスト送受信、添付の表示、過去履歴の追加取得。旧形式DMの本文には署名がありません。'],
  ['Messenger', '接続設定からFacebookに本人ログイン', 'この端末へ配信された1対1テキストの送受信・保存・検索と画像送信。受信画像の取得・表示、過去の暗号化バックアップの復元は未対応です。'],
];

export function HelpPanel({ close, provider, state }: { close: () => void; provider: Provider; state: Snapshot }) {
  const [copied, setCopied] = useState(false);
  // Fixed states and aggregate counts only. Never serialize snapshot wholesale.
  const diagnostics = JSON.stringify({ app: 'BeeperLocal', version: APP_VERSION, provider,
    connection: state.connection, receiving: state.receiving, storagePaused: !!state.storagePaused,
    errorCode: state.errorCode && /^[A-Z_]+$/.test(state.errorCode) ? state.errorCode : null,
    conversations: state.conversations.length, pendingSends: state.pendingSends.length }, null, 2);
  return <div className="settings-content">
    <div className="modal-heading"><h2 id="help-title">使い方・ベータ版の対応範囲</h2><button className="icon-button" aria-label="使い方を閉じる" onClick={close} autoFocus>×</button></div>
    <p className="help-intro">左のサービスを選び、本人のアカウントを連携してください。会話を選ぶと直近の履歴を取得します。保存済みのテキストは、通信が途切れても閲覧・検索できます。</p>
    <div className="help-services">{services.map(([name, setup, scope]) => <section key={name}><h3>{name}</h3><p><strong>{setup}</strong></p><p>{scope}</p></section>)}</div>
    <h3 className="help-open">日常の操作</h3>
    <ul className="help-shortcuts"><li>⌘Kで保存済みメッセージを検索。対象は選択中のサービスです。</li><li>Enterで改行、⌘Enterで送信。下書きは会話ごとに保持し、アプリを終了すると消えます。</li><li>保存を止めた場合は、接続設定から保存を再開して再接続してください。</li><li>送信結果が不明なときは、履歴か相手側で確認してから再送してください。</li></ul>
    <p className="settings-description">アプリ起動中は接続したサービスを同期し、未読をこのMacで集計します。通知は通知ボタンで許可できます。過去履歴はサービスが返す範囲まで取得し、保存済み履歴はページを追加して閲覧できます。削除は明示的な削除イベントに限って反映し、全サービスの完全な削除同期は未対応です。画像は全サービスで1枚ずつ送信できます（JPEG・PNG、4MBまで）。動画・その他のファイル送信と新規グループ作成は未対応です。保存した本文はこのMacで暗号化し、資格情報と鍵はキーチェーンで管理します。MCPは初期状態で停止しており、LINE・Slack・Instagram・X・Messengerそれぞれの「MCP接続」で、会話ごとに閲覧・検索と送信を許可できます。</p>
    <h3>Macのキーチェーン確認が出るとき</h3><p className="settings-description">鍵マークの確認には、このMacのログインパスワードを入力します。サービスのパスワードとは別です。信頼する配布元のBeeperLocalであることを確認し、macOSの確認画面で「常に許可」を選ぶと、同じ署名のアプリからの次回アクセスも許可できます。「許可」は今回だけの許可です。取り消した場合は、各サービスの再接続ボタンからやり直せます。</p><h3>困ったときの診断情報</h3><p className="settings-description">開発者に相談する際は、発生した操作と以下の情報を伝えてください。本文・相手名・アカウントID・トークンは含みません。</p>
    <textarea className="diagnostic-text" aria-label="共有用の診断情報" readOnly value={diagnostics} onFocus={event => event.target.select()}/>
    <button className="secondary" onClick={() => { void navigator.clipboard?.writeText(diagnostics).then(() => setCopied(true)).catch(() => setCopied(false)); }}>診断情報をコピー</button>
    {copied && <p className="settings-notice" role="status">診断情報をコピーしました</p>}
    <p className="version">BeeperLocal {APP_VERSION} · ベータ候補版</p>
  </div>;
}
