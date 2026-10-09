"""Collect the session from our own fresh, user-operated native login window."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

from .core import ROOT, ConnectorError


def native_prompt(operation):
    executable = (Path(sys.executable).parent / "beeperlocal-x-login" if getattr(sys, "frozen", False)
                  else ROOT / "bin/beeperlocal-x-login")
    proc = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, close_fds=True, bufsize=0,
                            env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "OS_ACTIVITY_MODE": "disable"})
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        proc.stdin.write(json.dumps({"op": operation, "protocol": 1}).encode() + b"\n")
        deadline, received = time.monotonic() + 920, bytearray()
        while b"\n" not in received:
            timeout = deadline - time.monotonic()
            if timeout <= 0 or not selector.select(timeout):
                raise ConnectorError("web_login_timeout")
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                raise ConnectorError("web_login_closed")
            received.extend(chunk)
            if len(received) > 1024 * 1024:
                raise ConnectorError("web_login_protocol_failed")
        result = json.loads(received.partition(b"\n")[0])
        if result.get("ok") is not True:
            code = result.get("error")
            raise ConnectorError(code if code in {"cancelled", "web_login_timeout"} else "web_login_protocol_failed")
        return result
    except ConnectorError:
        raise
    except Exception:
        raise ConnectorError("web_login_protocol_failed") from None
    finally:
        selector.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdin.close()
        proc.stdout.close()


def browser_login():
    cookie = native_prompt("web_login").get("cookies")
    if not isinstance(cookie, str) or "auth_token=" not in cookie or "ct0=" not in cookie or any(c in cookie for c in "\n\r"):
        raise ConnectorError("web_login_protocol_failed")
    return cookie


def chat_pin():
    pin = native_prompt("chat_pin").get("pin")
    if not isinstance(pin, str) or not 1 <= len(pin) <= 1024:
        raise ConnectorError("web_login_protocol_failed")
    return pin
