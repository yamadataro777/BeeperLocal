import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { CoreEvent, Request } from './types';

const demo = import.meta.env.DEV && new URLSearchParams(location.search).get('demo') === '1';
export const isDemo = demo;
const fixture = demo ? import('./fixture') : null;

export async function request<T>(value: Request): Promise<T> {
  if (fixture) return (await fixture).request(value) as Promise<T>;
  return invoke<T>('core_request', { request: value });
}

export async function subscribe(callback: (event: CoreEvent) => void) {
  if (fixture) return (await fixture).subscribe(callback);
  return listen<CoreEvent>('core-event', event => callback(event.payload));
}

export async function openSetup(provider: 'instagram' | 'slack') {
  // Stop this provider before its separate login process updates its session.
  await request({ op: 'stop', provider });
  if (fixture) return (await fixture).openSetup(provider);
  return invoke<void>('open_setup', { provider });
}

const errors: Record<string, string> = {
  IMAGE_TOO_LARGE: '画像は4MB・2,500万画素以内で選択してください。大きい画像は小さくしてから送信できます。',
  IMAGE_FORMAT_UNSUPPORTED: 'この画像を読み込めません。JPEGまたはPNGで保存し直してください。',
  SLACK_IMAGE_SCOPE_REQUIRED: 'Slack連携のファイル送信権限が必要です。ワークスペース側の許可を更新して再認証してください。ログインボタンが無効な場合は配布元の設定が必要です。',
  IG_RECONNECT_WAITING: 'Instagramとの通信が回復するのを待っています。1分間隔で自動的に再確認します。',
  SLACK_RECONNECT_WAITING: 'Slackとの通信が回復するのを待っています。5分間隔で自動的に再確認します。',
  CORE_NOT_FOUND: '接続プログラムが見つかりません。配布されたBeeperLocal.appをもう一度コピーしてください。',
  SETUP_OPEN_FAILED: 'ログイン画面を開けませんでした。配布フォルダの接続ファイルを開いてください。',
  NETWORK_ERROR: '通信できません。インターネット接続を確認してください。保存済みの会話は引き続き読めます。',
  HTTP_ERROR: 'サービスに接続できませんでした。時間をおいて再接続してください。',
  BAD_RESPONSE: 'サービスの応答を確認できませんでした。再接続しても続く場合は、この状態を開発者へお知らせください。',
  MESSENGER_SEND_UNKNOWN: 'Messengerへの送信結果が不明です。再送せず、履歴か相手側で確認してください。',
  MESSENGER_SENT_NOT_STORED: 'Messengerへの送信は確認できましたが、保存に失敗しました。再送せず履歴を確認してください。',
  "MESSENGER_LOGIN_REQUIRED": "接続設定からFacebookに本人ログインしてください。",
  "MESSENGER_AUTH_FAILED": "Messengerの認証を確認できません。接続設定から同じFacebookアカウントでログインし直してください。",
  "MESSENGER_LOGIN_CANCELLED": "Messengerの連携を中止しました。",
  "MESSENGER_LOGIN_IN_PROGRESS": "Facebookのログイン画面で本人確認を完了するか、連携を中止してください。",
  "MESSENGER_ADAPTER_MISSING": "Messenger接続プログラムがありません。アプリを再ビルドしてください。",
  "MESSENGER_REGISTRATION_UNKNOWN": "暗号化端末の登録結果が不明です。自動再登録せず接続を停止しました。",
  "MESSENGER_DEVICE_INVALID": "Messengerの保存済み端末鍵を確認できません。鍵をリセットせず停止しました。",
  "MESSENGER_STATE_LIMIT": "Messengerの端末状態が保存上限に達しました。受信を停止しました。",
  "MESSENGER_PERSIST_FAILED": "Messengerの受信データを保存できません。受信確認を返さず停止しました。",
  "MESSENGER_DECRYPT_FAILED": "Messengerのメッセージを復号できません。受信を停止しました。",
  "MESSENGER_PROTOCOL_ERROR": "Messengerの応答を確認できません。接続を停止しました。",
  "MESSENGER_CONNECTION_LOST": "Messengerとの通信が途切れました。接続を再確認します。",
  "MESSENGER_ALREADY_RUNNING": "別のMessenger接続が使用中です。検証用画面などを終了してから再接続してください。",
  "MESSENGER_DESKTOP_REQUIRED": "MessengerはBeeperLocalアプリのサービス一覧から操作してください。",
  X_DESKTOP_REQUIRED: "XはBeeperLocalアプリのサービス一覧から操作してください。",
  X_ADAPTER_MISSING: "X接続プログラムを起動できません。アプリの修正版が必要です。",
  X_LOGIN_REQUIRED: "接続設定からXにログインしてください。",
  X_UNLOCK_REQUIRED: "X Chatのパスコードで鍵を解除してください。",
  X_UNLOCK_FAILED: "Chatパスコードの解除に失敗しました。自動再試行はしていません。",
  X_KEY_CHANGED: "Xの登録鍵が変わっています。接続を停止しました。",
  X_SETUP_REQUIRED: "Xの公式アプリでChatを設定してから接続してください。",
  X_VERIFY_FAILED: "X Chatの署名・鍵を確認できません。今回の履歴は取り込まず停止しました。",
  X_ALREADY_RUNNING: "別のX接続画面が使用中です。独立版の接続画面を終了してください。",
  X_REQUEST_TIMEOUT: "Xへの接続がタイムアウトしました。",
  X_REQUEST_FAILED: "Xとの接続が停止しました。再接続してください。",
  X_PROTOCOL_ERROR: "Xの応答を確認できません。接続を停止しました。",
  X_SEND_UNKNOWN: "Xへの送信結果が不明です。再送せず、履歴か相手側で確認してください。",
  X_SENT_NOT_STORED: "Xは送信を受け付けましたが保存できませんでした。再送せず履歴を更新してください。",
  X_DIRECT_ONLY: "X Chatは既存の1対1テキスト会話に対応しています。",
  X_HISTORY_INCOMPLETE: "取得範囲を超える新着があるため受信確認を停止しました。履歴を更新してください。",
  X_LOGIN_TIMEOUT: "Xログインの待機時間を超えました。",
  X_LOGIN_CANCELLED: "Xの連携を中止しました。",
  X_LOGIN_FAILED: "Xの連携を完了できませんでした。",
  X_LOGIN_IN_PROGRESS: "Xの連携中です。本人確認を完了するか中止してください。",
  LINE_RECONNECT_WAITING: 'LINEとの通信が回復するのを待っています。1分間隔で自動的に再確認します。',
  SLACK_OAUTH_NOT_CONFIGURED: 'このビルドにはSlackの認証設定がありません。配布元で公開Client IDとPKCE対応の設定が必要です。',
  SLACK_OAUTH_FAILED: 'Slackの認証を完了できませんでした。もう一度ログインしてください。',
  SLACK_OAUTH_CANCELLED: 'Slackの承認が中止されました。',
  SLACK_OAUTH_PERMISSIONS_REQUIRED: 'Slackの閲覧・送信・画像の権限が不足しています。もう一度ログインして必要な権限を承認してください。ワークスペースの管理者による承認が必要な場合もあります。',
  SLACK_OAUTH_TIMEOUT: 'Slackの承認が時間切れになりました。もう一度ログインしてください。',
  SLACK_BROWSER_FAILED: 'ブラウザを開けませんでした。既定のブラウザ設定を確認してください。',
  SLACK_LOGIN_REQUIRED: 'Slackの本人認証が必要です。接続設定の「Slackにログイン」から設定できます。ワークスペースで承認されたUser OAuthトークンが必要です。',
  SLACK_SELECT_ONE: 'Slackの会話を1件選択してください。',
  SLACK_SEND_UNKNOWN: 'Slackの送信結果が不明です。再送せず履歴または相手側で確認してください。',
  SLACK_SENT_NOT_STORED: 'Slackは送信を受け付けましたが保存できませんでした。再送せず履歴を更新してください。',
  MISSING_SCOPE: 'SlackアプリのUser権限が不足しています。必要な権限を承認して再認証してください。',
  RATE_LIMITED: 'Slackの取得制限に達しました。時間をおいてから再取得してください。',

  LINE_LOGIN_REQUIRED: 'LINEの連携が必要です。「QRコードでLINEを連携」から始めてください。',
  LINE_SESSION_REVOKED: 'LINEのログインが無効になりました。本家BeeperやChrome版LINEとの再連携で、もう一方がログアウトする場合があります。使うアプリを決めてから、QRコードで再連携してください。保存履歴と下書きは残っています。',
  LINE_LOGIN_FAILED: 'LINEの連携を完了できませんでした。ネットワークとスマートフォンを確認して、もう一度お試しください。',
  LINE_LOGIN_UNKNOWN: 'スマートフォンでの承認後の結果を確認できませんでした。まず再接続して、ログイン状態を確認してください。',
  LINE_LOGIN_REPLACEMENT_REQUIRED: 'このMacにはLINEログインが保存されています。更新する場合は、下のチェックを入れてください。',
  LINE_LOGIN_IN_PROGRESS: 'LINEの連携中です。スマートフォンで承認するか、連携を中止してください。',
  IG_LOGIN_REQUIRED: 'Instagram接続.commandで本人ログイン後、Instagramへ再接続してください。',
  IG_AUTH_ACTION_REQUIRED: 'Instagramで本人確認が必要です。「Instagramにログイン」から公式サイトの専用画面を開いて進めてください。通知が届かない場合は、画面に表示される別の確認方法を選んでください。',
  IG_WEB_LOGIN_UNAVAILABLE: 'Instagramの専用ログイン画面を開けませんでした。最新版のBeeperLocal.appからやり直してください。',
  IG_LOGIN_CANCELLED: 'Instagramのログインを中止しました。保存済みの連携情報は変更していません。',
  IG_PASSWORD_REJECTED: 'Instagramがユーザー名またはパスワードを受け付けませんでした。Instagramのユーザー名とパスワードを確認してください。',
  IG_CODE_REJECTED: 'Instagramの確認コードが一致しないか、期限が切れています。認証アプリまたはSMSの新しいコードでやり直してください。',
  IG_ACCOUNT_ACTION_REQUIRED: 'Instagramアカウントの状態を確認する必要があります。公式Instagramアプリで案内を確認してください。',
  IG_LOGIN_REJECTED: 'Instagram側が今回のログインを拒否しました。パスワードの誤りかどうかは判別できません。公式Instagramアプリでログイン通知・本人確認を確認してください。',
  IG_ADAPTER_MISSING: 'Instagram接続プログラムが見つかりません。アプリを再ビルドしてください。',
  IG_PROTOCOL_ERROR: 'Instagramの応答を処理できませんでした。再接続してください。',
  IG_REQUEST_TIMEOUT: 'Instagramから時間内に応答がありませんでした。パスワードの誤りを示すものではありません。通信状態を確認して、しばらく待ってからやり直してください。',
  IG_REQUEST_FAILED: 'Instagramとの通信を完了できませんでした。パスワードの誤りかどうかは確認できていません。通信状態と公式Instagramの利用状況を確認してください。',
  IG_RESYNC_REQUIRED: 'Instagramの履歴を再取得する必要があります。再接続してください。',
  IG_SEND_UNKNOWN: '送信結果が不明です。自動再送せず、相手側か履歴で確認してください。',
  IG_SENT_NOT_STORED: 'Instagramが送信を受け付けましたが保存できませんでした。再送せず履歴を更新してください。',

  MCP_ACCESS_DENIED: 'このクライアントの権限を確認してください。',
  MCP_DISABLED: 'MCP接続は停止しています。',
  MCP_PORT_IN_USE: 'このポートは使えません。別のポート番号を指定してください。',
  MCP_START_FAILED: 'MCP接続を開始できませんでした。',
  MCP_CLIENT_LIMIT: '登録数の上限です。使わないクライアントの権限を取り消してください。',
  STORAGE_PAUSED: '保存を停止中です。保存管理から再開してください。',
  DELETE_CONFIRMATION_EXPIRED: '削除の確認期限が切れたか対象が変わりました。削除対象をもう一度確認してください。',
  SYNC_RETRY_EXHAUSTED: '再接続を続けて試しましたが回復しませんでした。ネットワークを確認して再接続してください。',
  CORE_STOPPED: '接続プロセスが停止しました。アプリを終了して、もう一度開いてください。',
  CORE_START_FAILED: '接続プロセスを起動できませんでした。アプリを開き直してください。',
  CORE_TIMEOUT: '処理結果を確認できませんでした。送信した場合は、再送する前に履歴を確認してください。',
  DESKTOP_ALREADY_RUNNING: 'BeeperLocalはすでに起動しています。開いているウィンドウを使用してください。',
  DESKTOP_NOT_CONNECTED: 'サービスへの接続を確認してから操作してください。保存済みの会話は引き続き読めます。',
  KEYCHAIN_UNAVAILABLE: 'Macのキーチェーンを利用できませんでした。Macへログインした状態で、接続をやり直してください。',
  KEYCHAIN_SESSION_AUTH_FAILED: 'Macのキーチェーン自体で認証エラーが出ています。作業を保存してMacを再起動し、ログイン後に接続をやり直してください。キーチェーンのリセット・削除は不要です。',
  KEYCHAIN_AUTH_FAILED: 'Mac側でキーチェーンの認証が成立しませんでした。パスワードの不一致かアクセス許可の問題かは、このエラーだけでは判別できません。',
  KEYCHAIN_INTERACTION_REQUIRED: 'Mac側の本人確認を表示できません。Macへログインした状態でアプリを開き直してください。',
  KEYCHAIN_ACCESS_DENIED: 'キーチェーンへのアクセスがキャンセルまたは拒否されました。再接続を押すまで確認は繰り返しません。再接続後、Macのログインパスワードで確認を完了してください。',
  KEYCHAIN_SIGNATURE_INVALID: '接続エンジンの署名をmacOSが確認できませんでした。アプリの修正版が必要です。',
  KEYCHAIN_WRITE_FAILED: 'キーチェーンへ保存できませんでした。Macのアクセス許可を確認してください。',
  CREDENTIALS_MISSING: 'このサービスのログインが必要です。接続設定から本人ログインしてください。',
  CREDENTIALS_INVALID: 'このサービスへの再ログインが必要です。接続設定から本人ログイン後、再接続してください。',
  LINE_REQUEST_FAILED: 'LINEへの接続を確認できませんでした。ネットワークと、このMacのLINEログイン状態を確認してください。',
  LINE_WATCH_FAILED: 'LINEの受信が停止しました。「履歴を更新」または「再接続」で再開してください。',
  LINE_RESYNC_REQUIRED: 'LINEから履歴の再取得が必要と通知されました。「履歴を更新」を押してください。',
  LINE_DECRYPT_FAILED: '一部のメッセージを復号できませんでした。LINEのログイン状態を確認してください。',
  LINE_SEND_UNKNOWN: '送信結果が不明です。自動再送はしていません。履歴か相手側で結果を確認してください。',
  LINE_SENT_NOT_STORED: 'LINEは送信を受け付けましたが、このMacへの保存に失敗しました。再送せず履歴を更新してください。',
  CONVERSATION_CHANGED: '会話が切り替わりました。宛先を確認してから送信してください。',
  CONVERSATION_UNAVAILABLE: 'この会話を開けませんでした。接続して会話一覧を更新してください。',
  ACCOUNT_CHANGED: 'サービスのアカウントが変わっています。接続設定を確認してください。',
  NO_SELECTION: '会話一覧から相手を選択してください。',
  LOCAL_DB_CORRUPT: '保存データの整合性を確認できません。データを上書きせず停止しました。',
  LOCAL_DB_KEY_MISMATCH: '保存データとキーチェーンの鍵が一致しません。データを上書きせず停止しました。',
  LOCAL_DB_KEY_MISSING: '保存データの暗号鍵が見つかりません。Macのキーチェーンを確認してください。',
  LOCAL_DB_UNAVAILABLE: '保存データを開けません。Macの空き容量とアクセス許可を確認してください。',
  INVALID_INPUT: '入力内容と、このサービスの送信上限を確認してください。',
};
export function errorText(error: unknown) {
  const code = typeof error === 'string' && /^[A-Z_]+$/.test(error) ? error : 'UNEXPECTED_ERROR';
  return errors[code] ?? '処理を完了できませんでした。接続を確認してもう一度操作してください。';
}
