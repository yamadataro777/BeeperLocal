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

const errors: Record<string, string> = {
  LINE_RECONNECT_WAITING: 'LINEとの通信が回復するのを待っています。1分間隔で自動的に再確認します。',
  SLACK_LOGIN_REQUIRED: 'Slackの本人認証が必要です。開発版のlogin slackでUser OAuth認証を設定してください。',
  SLACK_SELECT_ONE: 'Slackの会話を1件選択してください。',
  SLACK_SEND_UNKNOWN: 'Slackの送信結果が不明です。再送せず履歴または相手側で確認してください。',
  SLACK_SENT_NOT_STORED: 'Slackは送信を受け付けましたが保存できませんでした。再送せず履歴を更新してください。',
  MISSING_SCOPE: 'SlackアプリのUser権限が不足しています。必要な権限を承認して再認証してください。',
  RATE_LIMITED: 'Slackの取得制限に達しました。時間をおいてから再取得してください。',

  LINE_LOGIN_REQUIRED: 'LINEの連携が必要です。「QRコードでLINEを連携」から始めてください。',
  LINE_LOGIN_FAILED: 'LINEの連携を完了できませんでした。ネットワークとスマートフォンを確認して、もう一度お試しください。',
  LINE_LOGIN_UNKNOWN: 'スマートフォンでの承認後の結果を確認できませんでした。まず再接続して、ログイン状態を確認してください。',
  LINE_LOGIN_REPLACEMENT_REQUIRED: 'このMacにはLINEログインが保存されています。更新する場合は、下のチェックを入れてください。',
  LINE_LOGIN_IN_PROGRESS: 'LINEの連携中です。スマートフォンで承認するか、連携を中止してください。',
  IG_LOGIN_REQUIRED: 'Instagram接続.commandで本人ログイン後、Instagramへ再接続してください。',
  IG_AUTH_ACTION_REQUIRED: 'Instagramの本人確認が必要です。Instagram接続.commandから再ログインしてください。',
  IG_ADAPTER_MISSING: 'Instagram接続プログラムが見つかりません。アプリを再ビルドしてください。',
  IG_PROTOCOL_ERROR: 'Instagramの応答を処理できませんでした。再接続してください。',
  IG_REQUEST_TIMEOUT: 'Instagramへの接続がタイムアウトしました。',
  IG_REQUEST_FAILED: 'Instagramとの接続が停止しました。再接続してください。',
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
  KEYCHAIN_ACCESS_DENIED: 'キーチェーンへのアクセスがキャンセルまたは拒否されました。接続をやり直して、Mac側の確認を完了してください。',
  KEYCHAIN_SIGNATURE_INVALID: '接続エンジンの署名をmacOSが確認できませんでした。アプリの修正版が必要です。',
  KEYCHAIN_WRITE_FAILED: 'キーチェーンへ保存できませんでした。Macのアクセス許可を確認してください。',
  CREDENTIALS_MISSING: 'LINEのログインが必要です。接続設定の「QRコードでLINEを連携」から始めてください。',
  CREDENTIALS_INVALID: 'LINEへの再ログインが必要です。本人ログイン後、接続をやり直してください。',
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
