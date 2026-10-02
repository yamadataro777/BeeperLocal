# 一次資料

確認日: 2026-09-27。ここに記載した外部仕様と、コードを実際に動かした証拠は別です。現在の認証画面やプロバイダー仕様が変更された場合は、公式資料を再確認してください。

| ID | 資料 | このPoCに関係する点 |
|---|---|---|
| T1 | [Telegram: Creating your Telegram Application](https://core.telegram.org/api/obtaining_api_id) | API ID/hashの取得、第三者クライアント利用条件。 |
| T2 | [Telethon: Signing In](https://docs.telethon.dev/en/stable/basic/signing-in.html) | API資格情報、通常アカウントのログイン。TelethonはTelegram公式SDKではなく第三者ライブラリ。 |
| T3 | [Telethon: Sessions](https://docs.telethon.dev/en/stable/concepts/sessions.html) | StringSessionはアカウントへのアクセスを可能にするSecretであり、漏洩を防ぐ必要がある。 |
| T4 | [Telethon: TelegramClient](https://docs.telethon.dev/en/stable/modules/client.html) | Client設定、会話一覧、履歴取得、認証関連メソッド。 |
| S1 | [Slack: conversations.history](https://docs.slack.dev/reference/methods/conversations.history/) | User Tokenの履歴権限、カーソル・時刻によるページング、配布形態別のレート制限、スレッド・履歴制限。 |
| S2 | [Slack: conversations.list](https://docs.slack.dev/reference/methods/conversations.list/) | 会話種類別スコープと一覧ページング。 |
| S3 | [Slack: Tokens](https://docs.slack.dev/authentication/tokens/) | User Token、Bot Token等の違い、xoxp形式。 |
| S4 | [Slack: App manifest reference](https://docs.slack.dev/reference/app-manifest/) | `oauth_config.scopes.user`を含むマニフェスト構造。 |
| S5 | [Slack: auth.test](https://docs.slack.dev/reference/methods/auth.test/) | Tokenの認証先を確認する。 |
| K1 | [Python keyring documentation](https://keyring.readthedocs.io/en/latest/) | macOSバックエンド、Secretの保存、同じPython実行ファイルからのアクセスに関するセキュリティ注意点。 |
| P1 | [Telethon on PyPI](https://pypi.org/project/Telethon/) | 確認したバージョン1.45.0。 |
| P2 | [keyring on PyPI](https://pypi.org/project/keyring/) | 確認したバージョン25.7.0。 |

外部資料はこのZIPに転載していません。コードは公式APIの読み取り処理を実装しており、ブラウザの秘密情報抽出やプラットフォームの認可回避を実装していません。
