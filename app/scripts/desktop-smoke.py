"""Read-only live verification of a packaged Core. Never print private payloads."""
import argparse
import json
from pathlib import Path
import selectors
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    binary = args.app / "Contents" / "MacOS" / "beeperlocal-core"
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b""
    counter = 0
    events = []

    def call(request):
        nonlocal counter, buffer
        counter += 1
        print("stage=" + request["op"], file=sys.stderr, flush=True)
        process.stdin.write((json.dumps({"id": counter, "request": request}) + "\n").encode())
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            if b"\n" not in buffer:
                if not selector.select(timeout=min(1, deadline - time.monotonic())):
                    continue
                chunk = process.stdout.read(65536)
                if not chunk:
                    raise RuntimeError("CORE_STOPPED")
                buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                value = json.loads(line)
                if "event" in value:
                    events.append(value)
                if value.get("id") == counter:
                    if not value.get("ok"):
                        code = value.get("error", "CORE_ERROR")
                        raise RuntimeError(code if isinstance(code, str) and code.replace("_", "").isupper() else "CORE_ERROR")
                    return value["result"]
        raise RuntimeError("CORE_TIMEOUT")

    try:
        ready = call({"op": "ping"})
        if not ready.get("ready"):
            raise RuntimeError("CORE_NOT_READY")
        before = call({"op": "snapshot"})
        connected = call({"op": "connect"})
        result = {"packaged_core_started": True, "connection": connected["connection"],
                  "local_conversations_before": len(before["conversations"]),
                  "live_conversations": len(connected["conversations"]),
                  "selected_conversation_present": bool(connected["selectedId"]),
                  "real_send_executed": False}
        if connected["selectedId"]:
            history = call({"op": "messages", "conversationId": connected["selectedId"]})
            result["local_messages"] = len(history["messages"])
            result["recovery_receipt_present"] = bool(history["lastRecovery"])
            result["history_bounded"] = history["historyLimited"]
            texts = [m["text"] for m in history["messages"] if m["text"].strip()]
            if texts:
                found = call({"op": "search", "query": texts[0].strip()[:20]})
                result["live_saved_text_found_locally"] = bool(found["results"])
        stopped = call({"op": "stop"})
        result["watch_process_started"] = any(e.get("receiving") == "waiting" for e in events)
        result["stopped_cleanly"] = stopped["receiving"] == "stopped"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if connected["connection"] == "connected" and connected["conversations"] else 1
    except RuntimeError as error:
        print(json.dumps({"status": "FAILED", "code": str(error), "real_send_executed": False}))
        return 1
    except Exception:
        print('{"status":"FAILED","code":"UNEXPECTED_ERROR","real_send_executed":false}')
        return 1
    finally:
        selector.close()
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
