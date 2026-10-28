"""Tiny client for the local EasyEDA bridge (easyeda-api skill).

    python tools/eda.py windows
    python tools/eda.py exec <windowId|-> "<javascript body>"
"""
import json
import sys
import urllib.request

BASE = None


def base():
    global BASE
    if BASE:
        return BASE
    for port in range(49620, 49630):
        try:
            r = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1))
            if r.get("service") == "easyeda-bridge":
                BASE = f"http://127.0.0.1:{port}"
                return BASE
        except Exception:
            pass
    raise RuntimeError("easyeda-bridge not found on 49620-49629")


def windows():
    return json.load(urllib.request.urlopen(base() + "/eda-windows", timeout=5))


def execute(code, window_id=None):
    body = {"code": code}
    if window_id:
        body["windowId"] = window_id
    req = urllib.request.Request(base() + "/execute", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=40))
    except urllib.error.HTTPError as e:
        return {"httpError": e.code, "body": e.read().decode()[:2000]}


if __name__ == "__main__":
    if sys.argv[1] == "windows":
        print(json.dumps(windows(), indent=1))
    else:
        wid = None if sys.argv[2] == "-" else sys.argv[2]
        print(json.dumps(execute(sys.argv[3], wid), indent=1)[:6000])
