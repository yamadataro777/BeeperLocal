"""Opt-in live receive-only verification of the built Core; outputs counts/codes only.

Does not start a login or send, select a new account, reset keys, or replace the app.
The built Core itself reads native Keychain and commits to its Messenger database.
"""
import asyncio
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
import stat

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app/Contents/MacOS/beeperlocal-core"


class VerificationError(Exception):
    pass


class Client:
    def __init__(self):
        self.sequence = 0
        self.process = None
    async def start(self):
        self.process = await asyncio.create_subprocess_exec(str(CORE), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=8*1024*1024)
    async def request(self, op, **fields):
        self.sequence += 1
        self.process.stdin.write((json.dumps({"id": self.sequence,
            "request": {"provider": "messenger", "op": op, **fields}}, ensure_ascii=True) + "\n").encode())
        await self.process.stdin.drain()
        async def read():
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise VerificationError("CORE_STOPPED")
                response = json.loads(line)
                if response.get("event") == "fatal" or (response.get("id") == self.sequence and not response.get("ok")):
                    code = response.get("error")
                    raise VerificationError(code if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,80}", code) else "VERIFY_FAILED")
                if response.get("id") == self.sequence:
                    return response["result"]
        return await asyncio.wait_for(read(), 170)
    async def close(self):
        if self.process is None:
            return
        if self.process.stdin:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), 20)
        except TimeoutError:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


class SourceClient(Client):
    """Provider-isolated check, serialized by Messenger's own session lock.

    Other providers and the running desktop are not opened or stopped. Transport
    uses the signed bundled helper, while DesktopCore code runs from source.
    """
    async def start(self):
        self.process = await asyncio.create_subprocess_exec(sys.executable, "-B", str(Path(__file__).resolve()), "--source-worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=8*1024*1024)


async def source_worker():
    # Test harness only: exactly one provider, its own production session lock,
    # no GUI/global desktop lock or other providers' credentials.
    if not all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (0, 1)):
        return 2
    sys.path.insert(0, str(ROOT))
    from beeperlocal.desktop_messenger import MessengerDesktop
    from beeperlocal.messenger import MessengerSession
    from beeperlocal.errors import AppError
    logging.disable(logging.CRITICAL)
    core = MessengerDesktop(session_factory=lambda: MessengerSession(command=[str(CORE.parent / "beeperlocal-messenger")]))
    reader = asyncio.StreamReader(limit=96*1024)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    try:
        while line := await reader.readline():
            request = json.loads(line)
            identity = request.get("id")
            fields = request.get("request", {})
            if type(identity) is not int or fields.pop("provider", None) != "messenger":
                return 2
            try:
                result = await core.dispatch(fields)
                reply = {"id": identity, "ok": True, "result": result}
            except Exception as exc:
                reply = {"id": identity, "ok": False, "error": exc.code if isinstance(exc, AppError) else "VERIFY_FAILED"}
            print(json.dumps(reply), flush=True)
    finally:
        transport.close()
        await core.close()
    return 0


async def verify(report, client_factory=Client):
    client = client_factory()
    query = None
    identity = None
    original_message_id = None
    try:
        await client.start()
        await client.request("ping")
        report["core_started"] = True
        snapshot = await client.request("connect")
        report["connected"] = snapshot["connection"] == "connected" and snapshot["receiving"] == "waiting"
        report["conversation_count"] = len(snapshot["conversations"])
        count = 0
        for conversation in snapshot["conversations"]:
            history = await client.request("messages", conversationId=conversation["id"])
            count += len(history["messages"])
            if query is None:
                for message in history["messages"]:
                    if message["text"].strip():
                        query = message["text"].strip()[:100]
                        identity, original_message_id = conversation["id"], message["id"]
                        break
        report["saved_texts_in_display_window"] = count
        await client.request("stop")
    finally:
        await client.close()
    if query is None:
        report["restart_search"] = "not_tested_no_saved_text"
        return
    fresh = client_factory()
    try:
        await fresh.start()
        snapshot = await fresh.request("snapshot")
        result = await fresh.request("search", query=query)
        matches = [row for row in result["results"] if row["conversationId"] == identity and row["id"] == original_message_id]
        report["restarted_offline"] = snapshot["connection"] == "offline"
        report["restart_search_matches"] = len(matches)
        snapshot = await fresh.request("connect")
        report["reconnected"] = snapshot["connection"] == "connected" and snapshot["receiving"] == "waiting"
        await fresh.request("stop")
    finally:
        await fresh.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-core", action="store_true", help="Isolate Messenger from an already running desktop; use the signed transport")
    parser.add_argument("--source-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.source_worker:
        try:
            return asyncio.run(source_worker())
        except Exception:
            return 1
    report = {"provider": "messenger", "source": "source_core_with_signed_transport" if args.source_core else "signed_packaged_core",
              "observed_at_utc": datetime.now(timezone.utc).isoformat(), "outbound_user_messages": 0,
              "new_inbound_text": "not_proven_separately_from_import", "native_gui": "not_tested",
              "old_encrypted_backup": "unsupported", "usual_app_replaced": False,
              "restart_scope": "separate_core_and_transport_processes"}
    try:
        asyncio.run(verify(report, SourceClient if args.source_core else Client))
        report["result"] = "pass" if report.get("connected") and report.get("restart_search_matches", 0) > 0 and report.get("reconnected") else "incomplete"
    except VerificationError as exc:
        report["result"], report["error_code"] = "failed_closed", str(exc)
    except Exception:
        report["result"], report["error_code"] = "failed_closed", "VERIFY_FAILED"
    # The report contains only locally constructed fixed fields, counts and codes.
    path = ROOT / "docs" / ("messenger-live-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    with path.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps(report))
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
