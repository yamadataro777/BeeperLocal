# Slackの表示名・プロフィール画像

2026-10-02。Slackで画像を取得・表示する経路がなかったため、既存User OAuthからusers.infoで名前と画像を取得する処理を追加した。チャンネルの各投稿には投稿者名と画像、DM一覧・見出しには相手名と画像を表示する。チャンネル自体のアイコンは#のまま。画像が取得できない場合も会話は読み書きでき、権限不足は接続設定への案内として表示する。

## 設定

Slack管理画面のOAuth & Permissionsを下へスクロールし、**Scopes → User Token Scopes → Add an OAuth Scope → users:read**を追加する。その後、Reinstall to Haruo → Allowで再認可し、BeeperLocalのSlack接続設定で「再接続・一覧更新」を押す。上部のUser OAuth Tokenは発行済みトークンの表示欄で、権限の追加欄ではない。トークンをチャットやログへ貼らない。

プロフィールAPIにはUser tokenのusers:readが必要。本実装はメール閲覧権限を要求しない。[Slack公式 users.info](https://docs.slack.dev/reference/methods/users.info/)

## 実装

暗号化保存済みの会話と直近の投稿者、またはDM相手を対象に必要な時だけ取得する。任意のユーザーIDやURLをGUIから指定できない。名前と画像は最大128人・通常1時間のメモリ内キャッシュに限り、平文ファイルへ保存しない。停止・保存停止・アカウント切替時は破棄する。画像は許可したHTTPS CDNから上限付きで取得し、OAuthトークンを送らず、リダイレクトを追わない。GUIには画像データを渡し、CSPを広げない。権限不足は明示し、再接続で再確認する。

## 確認

修正時のCore全384件・GUI全32件成功。追加したプロフィール関連はCore10件・GUI3件。名前、画像の実デコード、DM一覧・見出し、権限不足時の案内、既存LINE表示を架空データで確認した。shell構文、offline demo、production build、正式署名・旧版互換性も成功。

通常アプリ0.8.5には同時に進められたLINE画像対応とともに本修正が同梱された。インストール済みCoreのSlack関連3モジュールを試験済みビルドと照合して一致を確認した。本作業から通常アプリを重ねて置換していない。

実認証の確認では、保存済みUser OAuth tokenにusers:readがまだなく、プロフィールAPIは権限不足だった。実画像取得とnative GUI実画面の観察は未完了。DM・別の相手からの返信の検証は本人指定で後回し。本作業の送信は0回。

[検証記録](slack-profiles-verification-20261002.json)
