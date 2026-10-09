# LINEの画像・スタンプ表示（Desktop 0.8.5）

2026-10-02。ユーザーからLINEのチャットで画像・スタンプが表示されないとの指摘を受けて実装。

## 原因と変更

旧Coreはcontent_typeが0以外のメッセージを取り込み時に除外し、画面にもテキスト用の吹き出ししかなかった。LINEの画像（1）とスタンプ（7）を履歴取得・受信の両方で正規化し、送受信の向き・時刻・メッセージidentityを保持して既存の暗号化SQLiteに保存する。会話一覧には「画像」「スタンプ」を表示する。

画像は同梱line-cliの既存download機能で取得・認証付き復号し、private stdout pipeでCoreへ渡す。Go側ではスタンプの数値STKIDのみをsticker_idとして履歴・受信JSONへ追加した。スタンプ画像は固定のLINE CDNから取得する。任意URL・redirectは受け付けない。

画面内の対象だけ読み込み、クリックで拡大。取得できない場合もメッセージを残し、再読み込みを表示する。画像の失敗でテキスト受信を停止しない。プロバイダーの送信処理・送信再試行は追加していない。

## 保存・境界

- メディア種別とスタンプIDは既存AES-GCM payload内。旧payloadにmediaがなくても読み込める。
- 画像本体はディスク保存せず、RAM内のみ。20 MiBまでのLINE添付をPillowで検証・最大1600pxへ縮小し、EXIF等を除去して表示用PNG/JPEGへ再生成する。
- IPCへ返す画像の元データは最大4 MiB、base64キャッシュは24 MiB・64件まで。ダウンロードは同時1件、待機16件まで。
- GUIの要求はローカルの会話hash・メッセージhashのみ。provider/account/conversationを暗号化保存レコードと照合する。LINEのID・添付鍵・任意URLをGUIへ公開しない。
- 保存停止、再ログイン、会話切替、切断、アプリ終了時に処理を中止・キャッシュ消去。CSP・外部MCPの許可操作を拡張しない。

## 対応範囲

1対1LINE会話の画像と静止画スタンプ。アニメーション・音声・カスタム文字は未対応。画像取得はline-cliの直近100件内のメッセージ、LINE側の保存期間と20 MiB上限に従う。失効・期限切れ・古い画像には取得できない表示を出す。再起動後の画像表示には再接続が必要。動画・音声・一般ファイル・グループ・既読は今回の対象外。

## 検証

Core401件、画面35件、Goのmessaging/cli/events、shell構文、offline demo、production build成功。画面全体では34件成功後、新規テストのSlackボタンselectorを修正し残る1件も成功。画像・スタンプ表示、拡大、失敗時の再読み込み、読み込み中のサービス切替は架空データで確認。公開スタンプ1点について実CDNの取得・表示用画像生成も確認。

正式署名6実行対象・87内蔵binary、旧版との相互署名要件を確認。通常のBeeperLocal.appを0.8.5へ更新し、全16ファイルのhash一致と配置後署名を確認。旧0.8.4はarchive/app-backupsに保全。

初回の実接続はLINE_LOGIN_REQUIREDで停止したが、その後ユーザーがスマートフォンで再連携。配置済みアプリのnative GUIでLINE接続・受信待機、実チャットの画像2件とスタンプ1件の表示を確認し、画像・スタンプそれぞれの拡大表示も確認した。確認後は元の会話へ戻した。本文・相手名・ID・実画像を診断ファイルへ保存せず、実メッセージ送信は0回。アニメーション・全種類のスタンプや全画像の表示を検証したものではない。

記録: [検証](line-media-verification-20261002.json)、[配置](line-media-install-20261002.json)、[実接続](line-media-live-20261002.json)。

CDN形式の根拠: [LINE Engineeringの公開実装例](https://engineering.linecorp.com/zh-hant/blog/chatbot-icon-switch/)。LINE CLIの元実装・ライセンスはvendor/line-cli/PROVENANCE.mdとLICENSEを保持。
