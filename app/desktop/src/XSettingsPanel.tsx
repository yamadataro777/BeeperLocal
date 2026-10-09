export function XSettingsPanel({ busy, connected, paused, connect, login, stop }: {
  busy: boolean; connected: boolean; paused: boolean; connect: () => void;
  login: () => void; stop: () => void;
}) {
  return <section aria-label="X接続">
    <p className="settings-description">このMacに保存したXログインで、取得済みのDM・参加済みグループを順番に同期し、テキストを送受信できます。</p>
    <p className="settings-description">X ChatはDM・参加済みグループの署名を確認して保存します。旧形式DMは署名のない履歴として表示します。取得できる過去履歴を追加でき、画像・動画・音声はクリックして表示できます。新規グループ作成・添付送信・消えるメッセージは未対応です。署名済みの削除イベントを受信すると保存本文も削除します。</p>
    <div className="settings-actions">
      <button className="primary" disabled={busy || paused} onClick={connect}>再接続・一覧更新</button>
      <button className="secondary" disabled={busy || !connected} onClick={stop}>受信を停止</button>
      <button className="secondary" disabled={busy || paused} onClick={login}>Xにログイン・再連携</button>
    </div>
    <p className="settings-description">保存停止中も、保存済みの履歴の閲覧と検索は利用できます。外部AIへの会話の許可は「MCP接続」で設定できます。</p>
  </section>;
}
