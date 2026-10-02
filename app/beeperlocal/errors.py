"""Only fixed, non-sensitive diagnostics may cross the CLI boundary."""
from __future__ import annotations

MESSAGES = {
    "LINE_RECONNECT_WAITING": "LINEとの通信が回復するのを待っています。間隔を空けて自動で再接続します。",
    "SLACK_SELECT_ONE": "Slackの送信・定期取得では会話を1件選択してください。既存の複数会話syncは利用できます。",
    "SLACK_LOGIN_REQUIRED": "Slack User OAuth認証が必要です。login slackで本人認証後に再接続してください。",
    "SLACK_SEND_UNKNOWN": "Slack送信結果が不明です。自動再送せず、履歴または相手側で確認してください。",
    "SLACK_SENT_NOT_STORED": "Slackは送信を受け付けましたが保存に失敗しました。再送せず履歴を更新してください。",
    "LINE_LOGIN_REQUIRED": "LINEの連携が必要です。接続設定からQRコードで連携してください。",
    "LINE_LOGIN_FAILED": "LINEの連携を完了できませんでした。ネットワークとスマートフォンを確認してください。",
    "LINE_LOGIN_UNKNOWN": "LINEの承認後の結果を確認できませんでした。再接続で状態を確認してください。",
    "LINE_LOGIN_REPLACEMENT_REQUIRED": "LINEログインが保存されています。更新する場合は画面で確認してください。",
    "LINE_LOGIN_IN_PROGRESS": "LINEを連携中です。承認するか連携を中止してください。",
    'IG_ADAPTER_MISSING': 'Instagram接続プログラムが見つかりません。アプリを再ビルドしてください。',
    'IG_LOGIN_REQUIRED': 'Instagram接続.commandで本人ログイン後、アプリから再接続してください。',
    'IG_AUTH_ACTION_REQUIRED': 'Instagram側で本人確認が必要です。Instagram接続.commandから再ログインしてください。',
    'IG_PROTOCOL_ERROR': 'Instagramの応答を安全に処理できませんでした。',
    'IG_REQUEST_TIMEOUT': 'Instagramの応答待ちが終了しました。',
    'IG_REQUEST_FAILED': 'Instagramへ接続できませんでした。再接続してください。',
    'IG_SESSION_NOT_SAVED': 'InstagramのセッションをKeychainに保存できませんでした。',
    'IG_DIRECT_ONLY': 'Instagramは通常の1対1テキストDMに対応しています。',
    'IG_SEND_UNKNOWN': '送信結果が不明です。自動再送せず、相手側か履歴で確認してください。',
    'IG_SENT_NOT_STORED': 'Instagramが送信を受け付けましたが保存できませんでした。再送せず履歴を更新してください。',
    'IG_RESYNC_REQUIRED': 'Instagramの履歴を再取得する必要があります。再接続してください。',

    "MCP_ACCESS_DENIED": "この接続先には指定された操作・会話への許可がありません。",
    "MCP_DISABLED": "ローカルMCP接続は無効です。接続設定で有効にしてください。",
    "MCP_PORT_IN_USE": "MCPの待受ポートを使用できません。設定で別のポートを選んでください。",
    "MCP_START_FAILED": "ローカルMCPを起動できませんでした。アプリを開き直してください。",
    "MCP_CLIENT_LIMIT": "接続先の登録上限です。使わない接続先を解除してください。",
    "STORAGE_PAUSED": "保存を停止しています。新しい取得・受信・送信を再開するには、保存管理で再開してください。",
    "DELETE_CONFIRMATION_EXPIRED": "削除確認の有効期限が切れたか、対象が変わりました。対象件数をもう一度確認してください。",
    "SYNC_RETRY_EXHAUSTED": "自動再接続の試行上限に達しました。ネットワークと選択中サービスのログイン状態を確認して再接続してください。",
    "DESKTOP_ALREADY_RUNNING": "BeeperLocalはすでに起動しています。開いているウィンドウを使用してください。",
    "DESKTOP_NOT_CONNECTED": "LINEへの接続を確認してから操作してください。保存済みの会話はオフラインでも読めます。",
    "CONVERSATION_CHANGED": "会話が切り替わりました。宛先を確認してから送信してください。",
    "CONNECTOR_CAPABILITY_UNSUPPORTED": "このproviderには指定された操作がまだ実装されていません。利用可能な操作は capabilities で確認できます。",
    "LINE_E2E_TIMEOUT": "今回の識別文と一致するrealtime返信を待機時間内に確認できませんでした。再送していません。再実行前に相手側の送信結果を確認してください。",
    "LINE_E2E_VERIFY_FAILED": "DBを開き直した検索で今回の送信とrealtime返信を確認できませんでした。CLOSEDにはしません。",
    "LINE_CLI_MISSING": "Mac上のline-cli実行ファイルが見つかりません。検証済みv0.4.0を使用してください。",
    "LINE_DIRECT_MID_REQUIRED": "raw LINE MID（1対1のU... / u...）を入力してください。表示名・Group・Roomは対象外です。",
    "LINE_REQUEST_FAILED": "line-cliから取得できませんでした。既存LINEログイン・接続・他プロセスの実行状況を確認してください。生の応答は表示しません。",
    "LINE_SEND_UNKNOWN": "送信結果を確認できません。LINE側で送信済みの可能性があるため再送していません。相手側または sync line で確認してから判断してください。",
    "LINE_SENT_NOT_STORED": "LINEから送信成功応答を取得しましたが、ローカル保存に失敗しました。再送せず、DBを確認して sync line で回収してください。",
    "LINE_DECRYPT_FAILED": "対象textを復号できないため保存を停止しました。line-cliのLetter Sealingセッションを確認してください。",
    "LINE_WATCH_FAILED": "LINE受信プロセスが停止しました。他のline watchやセッション状態を確認してください。保存漏れは sync line で回収できます。",
    "LINE_RESYNC_REQUIRED": "LINEが履歴再同期を要求しました。sync line で回収してからwatchを再開してください。",
    "UNSUPPORTED_PLATFORM": "実アカウント接続はmacOS限定です。demoとtestは他OSでも動きます。",
    "DEPENDENCY_MISSING": "依存パッケージがありません。bash scripts/setup.sh を実行してください。",
    "KEYCHAIN_UNAVAILABLE": "Keychainにアクセスできません。Macのキーチェーンを解除し、アクセス許可を確認してください。平文保存には切り替えません。",
    "KEYCHAIN_SESSION_AUTH_FAILED": "Macのキーチェーンがロック解除済みと報告していますが、OSの設定読み取りでも認証が失敗しています。作業を保存してMacを再起動し、ログイン後に接続をやり直してください。キーチェーンのリセットや削除は行わないでください。",
    "KEYCHAIN_AUTH_FAILED": "Mac側でキーチェーンの認証が成立しませんでした。パスワードの不一致とアプリのアクセス許可を、このエラーだけでは区別できません。",
    "KEYCHAIN_INTERACTION_REQUIRED": "Mac側の本人確認が必要ですが、現在の実行状態では確認を表示できません。Macへログインした状態でアプリを開き直してください。",
    "KEYCHAIN_ACCESS_DENIED": "キーチェーンへのアクセスがキャンセルまたは拒否されました。接続をやり直してMac側の確認を完了してください。",
    "KEYCHAIN_SIGNATURE_INVALID": "接続エンジンの署名情報をmacOSが確認できませんでした。アプリを再ビルドし、署名を検証してください。",
    "KEYCHAIN_WRITE_FAILED": "Keychainへの保存を確認できませんでした。新規Telegramセッションが作られた場合は公式アプリのDevicesで確認してください。",
    "CREDENTIALS_MISSING": "未ログインです。./run.sh login PROVIDER を実行してください。",
    "CREDENTIALS_INVALID": "認証が無効または期限切れです。./run.sh login PROVIDER で再認証してください。",
    "CREDENTIALS_CORRUPT": "保存した設定の形式が不正です。./run.sh login PROVIDER で再認証してください。",
    "INTERACTIVE_REQUIRED": "秘密情報は対話型Terminalでのみ入力できます。パイプ・環境変数・コマンド引数では受け付けません。",
    "INVALID_INPUT": "入力形式を確認してください。値そのものはログに出しません。",
    "NO_SELECTION": "取得する会話が未選択です。./run.sh select PROVIDER を実行してください。",
    "NO_CONVERSATIONS": "表示できる会話がありません。参加状況・取得権限・対象種類を確認してください。",
    "BOT_TOKEN_NOT_SUPPORTED": "このPoCは個人アカウント用です。SlackはUser OAuth Token、Telegramは本人の通常アカウントを使用してください。",
    "MISSING_SCOPE": "Slackの権限が不足しています。docs/SETUP_JA.mdのUser Token Scopesを確認し、変更後は再インストールしてください。",
    "MATRIX_ENCRYPTED_ROOM": "選択したMatrixルームはE2EE暗号化されています。Phase-0では復号を実装していないため、暗号化されていないルームを選択してください。",
    "MATRIX_LOGIN_UNSUPPORTED": "このMatrix homeserverでは選択したログイン方式を利用できません。Access Token方式を使うか、別のhomeserverを利用してください。",
    "CONVERSATION_UNAVAILABLE": "選択した会話を取得できません。参加・閲覧権限を確認し、selectをやり直してください。",
    "RATE_LIMITED": "レート制限で待機上限に達しました。追加取得せず停止しました。時間を置いて再実行してください。",
    "REQUEST_BUDGET_EXCEEDED": "安全なリクエスト上限に達しました。会話の選択数を減らして再実行してください。",
    "NETWORK_ERROR": "ネットワーク接続に失敗しました。接続とTLS証明書を確認してください。TLS検証の無効化はしません。",
    "HTTP_ERROR": "Slack APIがHTTPエラーを返しました。応答本文は秘密漏洩防止のため表示しません。",
    "API_ERROR": "APIがエラーを返しました。生の応答は表示しません。認証・権限・サービス稼働状況を確認してください。",
    "BAD_RESPONSE": "API応答の形式が想定と異なります。取得完了としては扱いません。",
    "PAGINATION_STALLED": "ページングが進まなくなったため停止しました。取得完了としては扱いません。",
    "SCAN_LIMIT_REACHED": "会話の走査上限に達しました。取得対象を絞ってください。",
    "TELEGRAM_CODE_INVALID": "Telegramの確認コードが不正または期限切れです。loginをやり直してください。",
    "TELEGRAM_PASSWORD_INVALID": "Telegramの2段階認証パスワードを確認してください。",
    "TELEGRAM_LOGIN_FAILED": "Telegramへのログインに失敗しました。API ID/hash、電話番号、公式アプリの通知を確認してください。",
    "ACCOUNT_CHANGED": "認証先アカウントが保存時と異なります。再ログイン・再選択してください。",
    "UNSAFE_PATH": "保存先の所有者・権限・シンボリックリンクを確認してください。",
    "NO_REPORT": "まだ検証レポートがありません。fetchまたはproofを実行してください。",
    "LOCAL_DB_UNAVAILABLE": "ローカルDBを安全に開けません。保存先の権限と空き容量を確認してください。平文DBには切り替えません。",
    "LOCAL_DB_CORRUPT": "ローカルDBの内容または認証タグが不正です。本文は表示せず停止しました。",
    "LOCAL_DB_KEY_MISSING": "ローカルDB暗号鍵がKeychainにありません。既存DBがある場合は新しい鍵を自動生成しません。",
    "LOCAL_DB_KEY_INVALID": "ローカルDB暗号鍵の形式が不正です。",
    "LOCAL_DB_KEY_MISMATCH": "Keychainの暗号鍵と既存ローカルDBが一致しません。DBを上書きせず停止しました。",
    "LOCAL_DB_SCHEMA_UNSUPPORTED": "ローカルDBのスキーマ版に対応していません。自動破壊・自動再作成はしません。",
    "LOCAL_DB_EMPTY": "ローカルDBにメッセージがありません。./run.sh sync を先に実行してください。",
    "UNEXPECTED_ERROR": "予期しないエラーで停止しました。秘密保護のため例外本文やトレースバックは表示していません。",
}

class AppError(Exception):
    def __init__(self, code: str):
        self.code = code if code in MESSAGES else "UNEXPECTED_ERROR"
        super().__init__(self.code)

    @property
    def safe_message(self) -> str:
        return MESSAGES[self.code]


def telegram_error(exc: Exception) -> AppError:
    if isinstance(exc, AppError):
        return exc
    name = type(exc).__name__
    if "Flood" in name or "SlowModeWait" in name:
        return AppError("RATE_LIMITED")
    if name in {"PhoneCodeInvalidError", "PhoneCodeExpiredError", "PhoneCodeEmptyError"}:
        return AppError("TELEGRAM_CODE_INVALID")
    if name == "PasswordHashInvalidError":
        return AppError("TELEGRAM_PASSWORD_INVALID")
    if name in {"AuthKeyUnregisteredError", "SessionRevokedError", "SessionExpiredError", "UserDeactivatedError", "AuthKeyDuplicatedError"}:
        return AppError("CREDENTIALS_INVALID")
    if name in {"ChannelPrivateError", "ChatAdminRequiredError", "PeerIdInvalidError", "ChannelInvalidError"}:
        return AppError("CONVERSATION_UNAVAILABLE")
    if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
        return AppError("NETWORK_ERROR")
    if name.startswith(("Phone", "ApiId")):
        return AppError("TELEGRAM_LOGIN_FAILED")
    return AppError("API_ERROR")
