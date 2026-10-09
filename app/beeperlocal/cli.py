from __future__ import annotations
import argparse
import asyncio
from contextlib import aclosing
from datetime import datetime, timedelta, timezone
import importlib.metadata
import importlib.util
import json
import logging
import os
from pathlib import Path
import platform
import re
import sys
import unittest
from . import __version__
from .credentials import MacKeychain, MacLocalKeyStore
from .errors import AppError, MESSAGES
from .models import FetchBatch, SUPPORTED_PROVIDERS, PROOF_PROVIDERS, PERSISTENCE_PROVIDERS, Conversation, StoredConversation, UnifiedMessage, make_report, finish_batch
from .privacy import preview_line, safe_text, secret_prompt
from .reporting import save_report, read_report


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error may echo a mistakenly pasted token or search text.
        self.print_usage(sys.stderr)
        self.exit(2, "引数を確認してください。秘密情報をコマンド引数に貼らず、対話入力を使ってください。\n")


def positive_limit(value: str) -> int:
    n = int(value)
    if not 1 <= n <= 50:
        raise argparse.ArgumentTypeError("limit must be 1..50")
    return n


def search_limit(value: str) -> int:
    n = int(value)
    if not 1 <= n <= 100:
        raise argparse.ArgumentTypeError("limit must be 1..100")
    return n


def list_limit(value: str) -> int:
    n = int(value)
    if not 1 <= n <= 500:
        raise argparse.ArgumentTypeError("list limit must be 1..500")
    return n


def wait_limit(value: str) -> int:
    n = int(value)
    if not 0 <= n <= 600:
        raise argparse.ArgumentTypeError("wait must be 0..600")
    return n


def parse_selection(value: str, size: int) -> list[int]:
    if not re.fullmatch(r"[0-9]+(?:\s*,\s*[0-9]+)*", value.strip()):
        raise AppError("INVALID_INPUT")
    indexes = list(dict.fromkeys(int(n.strip()) - 1 for n in value.split(",")))
    if not 1 <= len(indexes) <= 5 or any(i < 0 or i >= size for i in indexes):
        raise AppError("INVALID_INPUT")
    return indexes


def get_connector(provider, store, max_wait=240):
    from .connectors.registry import create_connector
    return create_connector(provider, store, max_wait=max_wait, notice=lambda text: print(text, file=sys.stderr))


def selected_records(provider, connector):
    return [StoredConversation(provider, connector.credentials["account_id"], Conversation.from_selection(c))
            for c in connector.credentials.get("selections", [])]


async def select_conversations(args) -> int:
    if not sys.stdin.isatty():
        raise AppError("INTERACTIVE_REQUIRED")
    store = MacKeychain()
    connector = get_connector(args.provider, store)
    if args.provider == "line":
        await choose_line_conversation(connector, args.list_limit)
        return 0
    if args.provider == "slack":
        choices = await connector.list_conversations(args.list_limit, args.types)
    else:
        choices = await connector.list_conversations(args.list_limit)
    if not choices:
        raise AppError("NO_CONVERSATIONS")
    print("取得を許可する会話を選択してください（最大5つ、最初は1つ推奨）。")
    for i, c in enumerate(choices, start=1):
        print(f"{i:3d}. [{safe_text(c.kind, 12)}] {safe_text(c.title, 70)}")
    if len(choices) >= args.list_limit:
        print("一覧は指定上限で打ち切っています。必要に応じて --list-limit 500 を指定してください。")
    selection = input("番号をカンマ区切りで入力（例 1 または 1,3）: ")
    indexes = parse_selection(selection, len(choices))
    credentials = store.load(args.provider)
    if credentials.get("account_id") != connector.credentials.get("account_id"):
        raise AppError("ACCOUNT_CHANGED")
    credentials["selections"] = [choices[i].selection() for i in indexes]
    with open_message_store() as db:
        db.upsert_conversations([StoredConversation(args.provider, credentials["account_id"], choices[i]) for i in indexes])
    store.save(args.provider, credentials)
    print(f"{args.provider}: {len(indexes)}会話をKeychainに保存しました。履歴取得は fetch / proof / sync で行います。")
    print("会話一覧APIの応答には最新メッセージ等が含まれる場合がありますが、ここでは保存していません。")
    return 0


async def choose_line_conversation(connector, limit=500):
    if not sys.stdin.isatty():
        raise AppError("INTERACTIVE_REQUIRED")
    choices = await connector.list_conversations(limit)
    if not choices:
        raise AppError("NO_CONVERSATIONS")
    print("利用する1対1の相手を1人選んでください。")
    for index, conversation in enumerate(choices, 1):
        print(f"{index:3d}. {safe_text(conversation.title, 70)}")
    indexes = parse_selection(input("相手の番号: "), len(choices))
    if len(indexes) != 1:
        raise AppError("INVALID_INPUT")
    conversation = choices[indexes[0]]
    await connector.select_mid(conversation.id, title=conversation.title)
    with open_message_store() as db:
        db.upsert_conversations(selected_records("line", connector))
    print("line: 相手をKeychainに保存しました。MIDの手入力は不要です。")


async def run_line_e2e(args):
    from .line_e2e import run_e2e
    if not sys.stdin.isatty():
        raise AppError("INTERACTIVE_REQUIRED")
    connector = get_connector("line", MacKeychain())
    await connector.connect()
    try:
        connector.selected_conversation()
    except AppError as exc:
        if exc.code != "NO_SELECTION":
            raise
        await choose_line_conversation(connector)
    try:
        return await run_e2e(connector, open_message_store, timeout=args.timeout,
                             notice=lambda line: print(line, flush=True))
    except (AppError, asyncio.CancelledError):
        print("line_e2e=OPEN | 自動再送はしていません。再実行前に相手側で送信結果を確認してください。", flush=True)
        raise


def demo_batches(limit: int = 50) -> list[FetchBatch]:
    batches = []
    origin = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    for offset, provider in enumerate(PROOF_PROVIDERS):
        batch = FetchBatch(provider, False, limit, conversations_requested=1, conversations_fetched=1)
        for i in range(limit):
            batch.messages.append(UnifiedMessage(provider, "fixture-account", "fixture-chat", str(i + 1),
                "fixture-sender", origin + timedelta(minutes=i * 2 + offset),
                f"TEST FIXTURE: {provider} の架空メッセージ {i + 1}", "DEMO会話"))
        batch.raw_items = limit
        batches.append(finish_batch(batch))
    return batches


def print_result(batches, report, preview=False):
    print("\n=== 統合タイムライン（この実行で取得した範囲・昇順） ===")
    if preview:
        print("注意: 本文を表示します。Terminalのスクロールバック・画面共有にも残ります。")
    messages = sorted([m for b in batches for m in b.messages], key=lambda m: m.sort_key)
    for message in messages:
        print(preview_line(message, preview=preview))
    print("\n=== 検証結果 ===")
    for row in report["providers"]:
        print(f"{row['provider']}: {row['status']} | real_messages={row['real_messages']} | volume={row.get('volume_status', 'N/A')}")
        for code in row.get("error_codes", []):
            print(f"  {code}: {MESSAGES.get(code, MESSAGES['UNEXPECTED_ERROR']).replace('PROVIDER', row['provider'])}")
    print("loop_status=" + report["loop_status"])
    print("volume_loop_status=" + report.get("volume_loop_status", "N/A"))


async def fetch_live(providers: list[str], limit: int, max_wait: int) -> list[FetchBatch]:
    batches = []
    for provider in providers:
        print(f"{provider}: 選択した会話の履歴を取得します。", file=sys.stderr)
        try:
            store = MacKeychain()
            connector = get_connector(provider, store, max_wait)
            batch = await connector.fetch(limit)
        except AppError as exc:
            batch = FetchBatch(provider, True, limit, errors=[exc.code])
        except Exception:
            batch = FetchBatch(provider, True, limit, errors=["UNEXPECTED_ERROR"])
        batches.append(batch)
    return batches


def batch_ready_for_persistence(batch: FetchBatch) -> bool:
    if batch.provider in {"line", "instagram"}:
        if batch.provider == "instagram":
            from .instagram_sync import history_receipt as line_history_receipt
        else:
            from .sync import line_history_receipt
        try:
            line_history_receipt(batch)
            return True
        except AppError:
            return False
    return bool(
        batch.live
        and batch.messages
        and not batch.errors
        and batch.normalization_errors == 0
        and batch.conversations_requested > 0
        and batch.conversations_fetched == batch.conversations_requested
        and all(m.provider == batch.provider for m in batch.messages)
    )


async def run_live(args) -> int:
    providers = list(PROOF_PROVIDERS) if args.command == "proof" else [args.provider]
    batches = await fetch_live(providers, args.limit, args.max_wait)
    report = make_report(batches)
    print_result(batches, report, args.preview)
    name = "last-proof.json" if args.command == "proof" else f"last-fetch-{args.provider}.json"
    path = save_report(report, name)
    print(f"本文を含まないレポート: {path}")
    if args.command == "proof":
        return 0 if report["loop_status"] == "CLOSED" else 1
    return 0 if any(r["provider"] == args.provider and r["status"] == "PASS" for r in report["providers"]) else 1


async def run_sync(args) -> int:
    providers = [args.provider] if args.provider else list(PROOF_PROVIDERS)
    batches = await fetch_live(providers, args.limit, args.max_wait)
    report = make_report(batches)
    print_result(batches, report, args.preview)
    bad = [b.provider for b in batches if not batch_ready_for_persistence(b)]
    if bad:
        print("local_store=NOT_WRITTEN（取得が完全でないproviderがあるため、部分保存しません）")
        save_report(report, "last-sync.json")
        return 1

    from .storage import EncryptedMessageStore, db_exists, default_db_path
    key_store = MacLocalKeyStore()
    key = key_store.load() if db_exists() else key_store.load_or_create()
    messages = sorted([m for b in batches for m in b.messages], key=lambda m: m.sort_key)
    with EncryptedMessageStore(key) as db:
        if providers == ["line"]:
            from .sync import persist_line_history
            receipt, stats = persist_line_history(db, batches[0])
            print_recovery(receipt, stats)
        else:
            stats = db.upsert(messages, conversations=[c for batch in batches for c in batch.conversations])
        counts = db.count_by_provider()
        total = db.total_count()
    save_report(report, "last-sync.json")
    print(f"local_store=WRITTEN | processed={stats['processed']} inserted={stats['inserted']} updated={stats['updated']} total={total}")
    print("provider_counts=" + ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())))
    print(f"db={default_db_path()}")
    print("本文・会話名・送信者・provider側IDはAES-256-GCM暗号化payload内。SQLiteに平文FTSは作成していません。")
    return 0


def open_message_store():
    from .storage import EncryptedMessageStore, db_exists
    keys = MacLocalKeyStore()
    return EncryptedMessageStore(keys.load() if db_exists() else keys.load_or_create())


def print_recovery(receipt, stats):
    print(f"line_history=RECOVERED | coverage=BOUNDED | fetched={receipt.raw_items} "
          f"stored_text={receipt.stored_messages} excluded={receipt.excluded_events} "
          f"inserted={stats['inserted']} updated={stats['updated']} "
          f"limit_reached={str(receipt.history_limited).lower()}", flush=True)
    print("直近履歴の回収結果です。過去履歴全体・削除・受信位置との完全な連続性は未確認です。", flush=True)


def run_sync_status(args):
    from .storage import db_exists
    from .models import iso
    if not db_exists():
        print("line_history=NOT_RECORDED | local_db=NOT_CREATED")
        return 0
    credentials = MacKeychain().load(args.provider)
    selections = credentials.get("selections")
    if not selections:
        raise AppError("NO_SELECTION")
    try:
        if not isinstance(selections, list) or len(selections) != 1:
            raise ValueError()
        record = StoredConversation(args.provider, credentials["account_id"],
                                    Conversation.from_selection(selections[0]))
    except (ValueError, TypeError, KeyError):
        raise AppError("CREDENTIALS_CORRUPT") from None
    with open_message_store() as db:
        receipt = db.get_sync_receipt(record)
    if receipt is None:
        print("line_history=NOT_RECORDED")
    else:
        print(f"line_history=RECORDED | coverage=BOUNDED | last_recovery={iso(receipt.completed_at)} "
              f"requested_limit={receipt.requested_limit} fetched={receipt.raw_items} "
              f"stored_text={receipt.stored_messages} excluded={receipt.excluded_events} "
              f"limit_reached={str(receipt.history_limited).lower()}")
    print("前回のローカル履歴回収の記録です。現在の接続状態や完全同期を示すものではありません。")
    return 0


async def run_send(args) -> int:
    from .connectors.registry import require_capability
    require_capability(args.provider, "send_text")
    connector = get_connector(args.provider, MacKeychain())
    text = secret_prompt("送信するtext（入力非表示、Enterで1回送信）: ")
    # Open/verify the existing DB before any remote mutation.
    with open_message_store() as db:
        db.upsert_conversations(selected_records(args.provider, connector))
        try:
            result = await connector.send_text(text)
        except asyncio.CancelledError:
            print("LINE_SEND_UNKNOWN: " + MESSAGES["LINE_SEND_UNKNOWN"], file=sys.stderr)
            raise
        try:
            stats = db.upsert([result.message], conversations=selected_records(args.provider, connector))
        except Exception:
            raise AppError("LINE_SENT_NOT_STORED") from None
    print(f"line_send=ACKNOWLEDGED | encrypted={str(result.encrypted).lower()} | local_store=WRITTEN | inserted={stats['inserted']}")
    print("送信成功応答とローカル保存を確認しました。別アカウント側の受信を確認してください。")
    return 0


async def run_watch(args) -> int:
    from .connectors.registry import require_capability
    require_capability(args.provider, "watch")
    connector = get_connector(args.provider, MacKeychain())
    received = 0
    seen = set()
    with open_message_store() as db:
        if not args.from_now:
            from .sync import recover_line_history
            print("line_history=RECOVERING | 受信開始前に選択会話の直近履歴を回収します。", flush=True)
            receipt, stats = await recover_line_history(connector, db, limit=args.recovery_limit)
            print_recovery(receipt, stats)
        else:
            db.upsert_conversations(selected_records(args.provider, connector))
            print("line_history=SKIPPED | --from-now指定のため履歴回収を省略します。", flush=True)
        print("line_watch=STARTING | 選択した1対1会話のtextを暗号化保存します。", flush=True)
        print("既存セッションと受信位置を復元します。Ctrl-Cで停止。", flush=True)
        try:
            async with asyncio.timeout(args.timeout if args.timeout else None):
                async with aclosing(connector.watch(timeout=args.timeout, from_now=args.from_now)) as stream:
                    async for message in stream:
                        stats = db.upsert([message], conversations=selected_records(args.provider, connector))
                        print(f"line_realtime=STORED | direction={message.direction} | inserted={stats['inserted']} updated={stats['updated']}", flush=True)
                        if message.direction == "incoming":
                            if args.max_messages or args.timeout:
                                if message.id not in seen:
                                    received += 1
                                    seen.add(message.id)
                            else:
                                # Continuous daemon must not retain every ID in memory.
                                received += stats["inserted"]
                        if args.max_messages and received >= args.max_messages:
                            break
        except TimeoutError:
            pass
    print(f"line_watch=STOPPED | incoming_unique={received}")
    return 0 if received else 1


async def run_conversations(args):
    if args.refresh:
        if not args.provider:
            raise AppError("INVALID_INPUT")
        connector = get_connector(args.provider, MacKeychain())
        conversations = await connector.list_conversations(500)
        records = [StoredConversation(args.provider, connector.credentials["account_id"], c) for c in conversations]
        with open_message_store() as db:
            db.upsert_conversations(records)
    with open_message_store() as db:
        records = db.list_conversations(provider=args.provider)
    print(f"local_conversations={len(records)}")
    for index, record in enumerate(records, 1):
        title = safe_text(record.conversation.title, 70) if args.names else "[会話名非表示]"
        print(f"{index:3d}. [{record.provider}] conversation={record.id[:12]} {title}")
    return 0


def run_messages(args):
    connector = get_connector(args.provider, MacKeychain())
    records = selected_records(args.provider, connector)
    if not records:
        raise AppError("NO_SELECTION")
    with open_message_store() as db:
        for record in records:
            for message in db.list_messages(record.provider, record.account_id, record.conversation.id, limit=args.limit):
                print(preview_line(message, preview=args.preview))
    return 0


def run_search(args) -> int:
    from .storage import EncryptedMessageStore, db_exists
    if not db_exists():
        raise AppError("LOCAL_DB_EMPTY")
    query = secret_prompt("検索語（入力非表示・shell historyに残しません）: ")
    key = MacLocalKeyStore().load()
    with EncryptedMessageStore(key) as db:
        if db.total_count() == 0:
            raise AppError("LOCAL_DB_EMPTY")
        results, scanned = db.search(query, provider=args.provider, limit=args.limit)
    print(f"local_search: matches={len(results)} scanned={scanned}")
    if args.preview:
        print("注意: マッチした本文を表示します。Terminalのスクロールバック・画面共有にも残ります。")
    for message in results:
        print(preview_line(message, preview=args.preview))
    if not results:
        print("一致なし。Phase-1検索は完全一致ではなく、復号後の単純な部分文字列検索です。")
    return 0


def run_db_status() -> int:
    from .storage import EncryptedMessageStore, db_exists, default_db_path
    if not db_exists():
        print("local_db=NOT_CREATED")
        print(f"db={default_db_path()}")
        return 0
    key = MacLocalKeyStore().load()
    with EncryptedMessageStore(key) as db:
        counts = db.count_by_provider()
        total = db.total_count()
    print(f"local_db=OK | total={total}")
    for provider, count in sorted(counts.items()):
        print(f"{provider}: {count}")
    print(f"db={default_db_path()}")
    print("保存形式: message payload AES-256-GCM / key macOS Keychain / plaintext FTSなし")
    return 0


def run_reset_local() -> int:
    if not sys.stdin.isatty():
        raise AppError("INTERACTIVE_REQUIRED")
    print("ローカル保存メッセージDBと、そのDB専用暗号鍵を削除します。Matrix/Slackのログイン資格情報は削除しません。")
    if input("削除する場合は DELETE LOCAL と入力: ") != "DELETE LOCAL":
        print("中止しました。")
        return 0
    from .storage import delete_database_files
    removed = delete_database_files()
    MacLocalKeyStore().delete()
    print(f"local_data=DELETED | files_removed={removed}")
    return 0


def doctor(check_keychain: bool) -> int:
    print(f"BeeperLocal {__version__}")
    print(f"Python: {platform.python_version()} | OS: {platform.system()} {platform.release()} | CPU: {platform.machine()}")
    okay = sys.version_info >= (3, 11)
    for name, dist in (("telethon", "Telethon"), ("keyring", "keyring"), ("cryptography", "cryptography")):
        present = importlib.util.find_spec(name) is not None
        version = importlib.metadata.version(dist) if present else "MISSING"
        print(f"{dist}: {version}")
        okay = okay and present
    if sys.platform != "darwin":
        print("実接続/Keychain: macOS専用。demo / test はこのOSでも実行可能。")
        okay = False
    if importlib.util.find_spec("telethon") is not None:
        from .connectors.telegram import create_client
        async def check_constructor():
            client = create_client({"api_id": 1, "api_hash": "0" * 32, "session": ""})
            if client.session.__class__.__name__ != "StringSession":
                raise AppError("BAD_RESPONSE")
        asyncio.run(check_constructor())
        print("Telethon constructor: OK（通信なし）")
    if check_keychain:
        store = MacKeychain()
        store.probe()
        print("Keychain: write/read/delete probe OK（既存アカウント情報・DB鍵は表示しません）")
    else:
        print("Keychain実機検証: 未実施。doctor --check-keychain で確認。")
    return 0 if okay else 1


def parser() -> Parser:
    p = Parser(description="BeeperLocal Phase-1: ローカル取得・暗号化保存・検索PoC")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    d = sub.add_parser("doctor", help="環境診断（アカウントへの接続なし）")
    d.add_argument("--check-keychain", action="store_true")
    demo = sub.add_parser("demo", help="架空データのみ。実接続の証拠にはしない")
    demo.add_argument("--limit", type=positive_limit, default=50)
    demo.add_argument("--preview", action="store_true")
    login = sub.add_parser("login", help="本人操作の対話ログイン")
    login.add_argument("provider", choices=SUPPORTED_PROVIDERS)
    choose = sub.add_parser("select", help="取得を許可する会話を選ぶ")
    choose.add_argument("provider", choices=SUPPORTED_PROVIDERS)
    choose.add_argument("--list-limit", type=list_limit, default=100)
    choose.add_argument("--types", choices=("public_channel,private_channel,im,mpim", "public_channel", "im", "private_channel", "mpim"), default="public_channel,private_channel,im,mpim", help="Slackの会話種類")
    for name in ("fetch", "proof"):
        cmd = sub.add_parser(name, help="1サービス取得" if name == "fetch" else "Matrix+Slackの最小実接続統合検証")
        if name == "fetch":
            cmd.add_argument("provider", choices=SUPPORTED_PROVIDERS)
        cmd.add_argument("--limit", type=positive_limit, default=50)
        cmd.add_argument("--preview", action="store_true", help="本文を明示的にTerminal表示する")
        cmd.add_argument("--max-wait", type=wait_limit, default=240, help="Slack再試行の総待機秒数上限。無制限には待たない")
    sync = sub.add_parser("sync", help="実メッセージを取得し、暗号化してローカルSQLiteへupsert")
    sync.add_argument("provider", nargs="?", choices=PERSISTENCE_PROVIDERS, help="省略時はMatrix+Slack。単独指定も可")
    sync.add_argument("--limit", type=positive_limit, default=50)
    sync.add_argument("--preview", action="store_true")
    sync.add_argument("--max-wait", type=wait_limit, default=240)
    search = sub.add_parser("search", help="ローカル暗号化DBを復号しながら部分文字列検索。検索語は対話入力")
    search.add_argument("--provider", choices=PERSISTENCE_PROVIDERS)
    search.add_argument("--limit", type=search_limit, default=20)
    search.add_argument("--preview", action="store_true", help="マッチ本文をTerminal表示する")
    send = sub.add_parser("send", help="選択済み会話へtextを1回送信し暗号化保存（自動再送なし）")
    send.add_argument("provider", choices=PERSISTENCE_PROVIDERS)
    watch = sub.add_parser("watch", aliases=["daemon"], help="LINE realtime / Slack定期取得を暗号化保存（本文・IDは表示しない）")
    watch.add_argument("provider", choices=PERSISTENCE_PROVIDERS)
    watch.add_argument("--timeout", type=wait_limit, default=0, help="受信待機秒数。0=無期限、最大600秒")
    watch.add_argument("--max-messages", type=wait_limit, default=0, help="選択会話の異なるincoming N件で終了。0=待機継続")
    watch.add_argument("--from-now", action="store_true", help="line-cliの保存済み受信位置を破棄して現在から開始")
    watch.add_argument("--recovery-limit", type=search_limit, default=50,
                       help="受信開始前に回収する直近履歴件数（1〜100、既定50）。--from-nowでは省略")
    sync_status = sub.add_parser("sync-status", help="選択会話の前回履歴回収結果をローカル表示（現在の接続状態ではない）")
    sync_status.add_argument("provider", choices=("line",))
    e2e = sub.add_parser("line-e2e", help="LINEを1往復し、realtime保存とDB再open後の検索を自動確認")
    e2e.add_argument("--timeout", type=wait_limit, default=300, help="最大待機秒数（1〜600）")
    e2e.set_defaults(provider="line")
    catalog = sub.add_parser("conversations", help="Coreの暗号化会話一覧。--refreshでproviderから更新")
    catalog.add_argument("provider", nargs="?", choices=PERSISTENCE_PROVIDERS)
    catalog.add_argument("--refresh", action="store_true")
    catalog.add_argument("--names", action="store_true", help="会話名を明示的に表示する")
    messages = sub.add_parser("messages", help="選択済み会話のローカル保存メッセージを表示")
    messages.add_argument("provider", choices=PERSISTENCE_PROVIDERS)
    messages.add_argument("--limit", type=search_limit, default=50)
    messages.add_argument("--preview", action="store_true")
    sub.add_parser("capabilities", help="同じconnector interfaceで利用できる操作を表示")
    sub.add_parser("db-status", help="本文を表示せずローカルDB件数を確認")
    sub.add_parser("reset-local", help="ローカルメッセージDBとDB暗号鍵を削除")
    sub.add_parser("report", help="直近のproofレポート（本文なし）")
    sub.add_parser("test", help="ローカル単体・疑似APIテスト。実接続はしない")
    forget = sub.add_parser("forget", help="providerのKeychain情報のみ削除（サービス側の失効ではない）")
    forget.add_argument("provider", choices=SUPPORTED_PROVIDERS)
    return p


def main(argv=None) -> int:
    logging.disable(logging.CRITICAL)
    if os.name == "posix":
        os.umask(0o077)
    args = parser().parse_args(argv)
    try:
        if getattr(args, "provider", None) == "messenger":
            raise AppError("MESSENGER_DESKTOP_REQUIRED")
        if getattr(args, "provider", None) == "x":
            # X uses its own metadata/store and GUI onboarding; never route it
            # through the old CLI's default provider Keychain or send path.
            raise AppError("X_DESKTOP_REQUIRED")
        if getattr(args, "provider", None) == "slack" and args.command in {"send", "watch", "daemon"}:
            from .slack_cli import run_slack
            return asyncio.run(run_slack(args))
        if getattr(args, "provider", None) == "instagram":
            from .instagram_cli import run_instagram
            return asyncio.run(run_instagram(args))
        if args.command == "demo":
            batches = demo_batches(args.limit)
            print("DEMO: 以下は全て架空データです。ネットワーク通信・Keychainアクセス・本文のファイル保存はありません。")
            print_result(batches, make_report(batches, demo=True), args.preview)
            return 0
        if args.command == "test":
            root = Path(__file__).resolve().parent.parent
            suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        if args.command == "doctor":
            return doctor(args.check_keychain)
        if args.command == "login":
            from .auth import login_slack, login_telegram, login_matrix
            store = MacKeychain()
            handlers = {"telegram": login_telegram, "slack": login_slack, "matrix": login_matrix}
            if args.provider == "line":
                from .connectors.line import attach_session
                handlers["line"] = attach_session
            asyncio.run(handlers[args.provider](store))
            print(f"{args.provider}: ログイン確認・Keychain保存が完了しました。")
            print(f"次: ./run.sh select {args.provider}")
            return 0
        if args.command == "select":
            return asyncio.run(select_conversations(args))
        if args.command in {"fetch", "proof"}:
            return asyncio.run(run_live(args))
        if args.command == "sync":
            return asyncio.run(run_sync(args))
        if args.command == "sync-status":
            return run_sync_status(args)
        if args.command == "send":
            return asyncio.run(run_send(args))
        if args.command in {"watch", "daemon"}:
            return asyncio.run(run_watch(args))
        if args.command == "line-e2e":
            if args.timeout == 0:
                raise AppError("INVALID_INPUT")
            return asyncio.run(run_line_e2e(args))
        if args.command == "conversations":
            return asyncio.run(run_conversations(args))
        if args.command == "messages":
            return run_messages(args)
        if args.command == "capabilities":
            from .connectors.registry import PROVIDERS
            for provider, (_, capabilities) in PROVIDERS.items():
                print(provider + ": " + ", ".join(sorted(capabilities)))
            return 0
        if args.command == "search":
            return run_search(args)
        if args.command == "db-status":
            return run_db_status()
        if args.command == "reset-local":
            return run_reset_local()
        if args.command == "report":
            print(json.dumps(read_report(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "forget":
            if not sys.stdin.isatty():
                raise AppError("INTERACTIVE_REQUIRED")
            print("削除対象はこのPoCのprovider認証情報と会話選択だけです。ローカルDBとDB鍵は残ります。")
            if input("削除する場合は DELETE と入力: ") != "DELETE":
                print("中止しました。")
                return 0
            MacKeychain().delete(args.provider)
            print("Keychainから削除しました。サービス側の失効手順はdocs/SETUP_JA.mdを参照してください。")
            return 0
    except AppError as exc:
        print(f"{exc.code}: {exc.safe_message.replace('PROVIDER', getattr(args, 'provider', 'matrix / slack') or 'matrix / slack')}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("中止しました。", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 1
    except Exception:
        print("UNEXPECTED_ERROR: " + MESSAGES["UNEXPECTED_ERROR"], file=sys.stderr)
        return 1
    return 1
