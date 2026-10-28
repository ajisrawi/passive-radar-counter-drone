"""DeepPCB Public API v1 client (spec: deeppcb.json). Key from env var DEEPPCB_API_KEY.

    python tools/deeppcb_client.py submit board_a path/to/board.kicad_pcb [EmptyBoard|CurrentProtectedWiring]
    python tools/deeppcb_client.py confirm <boardId>
    python tools/deeppcb_client.py status <boardId>
    python tools/deeppcb_client.py download <boardId> <revision> <type> <out_file>
    python tools/deeppcb_client.py balance

Board ids are recorded in hardware/deeppcb_boards.json.
"""
import json
import os
import sys
import uuid

import requests

BASE = "https://api.deeppcb.ai/api/v1"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REG = os.path.join(HW, "deeppcb_boards.json")


def H():
    return {"x-deeppcb-api-key": os.environ["DEEPPCB_API_KEY"], "Accept": "application/json"}


def show(r):
    try:
        body = r.json()
    except ValueError:
        body = r.text[:2000]
    return {"http": r.status_code, "body": body}


def registry():
    return json.load(open(REG)) if os.path.exists(REG) else {}


def submit(name, path, routing="EmptyBoard"):
    """path: .kicad_pcb; the .kicad_pro with the same stem must sit next to it."""
    req_id = f"{name}-{uuid.uuid4().hex[:8]}"
    pro = os.path.splitext(path)[0] + ".kicad_pro"
    with open(path, "rb") as f, open(pro, "rb") as fp:
        r = requests.post(f"{BASE}/boards", headers=H(), timeout=300,
                          data={"routingType": routing, "boardName": name, "requestId": req_id,
                                # required by the API; .invalid never resolves (RFC 2606), so no design data
                                # leaves DeepPCB through it - status is polled instead
                                "webhookUrl": os.environ.get("DEEPPCB_WEBHOOK", "https://deeppcb-hook.invalid/webhook"),
                                "webhookToken": uuid.uuid4().hex},
                          files={"kicadBoardFile": (os.path.basename(path), f, "application/octet-stream"),
                                 "kicadProjectFile": (os.path.basename(pro), fp, "application/octet-stream")})
    res = show(r)
    if r.status_code in (200, 201, 202):
        board_id = res["body"] if isinstance(res["body"], str) else res["body"].get("boardId", res["body"])
        reg = registry()
        reg[name] = {"boardId": str(board_id).strip('"'), "requestId": req_id, "file": path, "routingType": routing}
        json.dump(reg, open(REG, "w"), indent=1)
    return res


def confirm(board_id):
    return show(requests.patch(f"{BASE}/boards/{board_id}/confirm", headers=H(), timeout=120))


def status(board_id):
    res = show(requests.get(f"{BASE}/boards/{board_id}", headers=H(), timeout=60))
    b = res["body"]
    if isinstance(b, dict):
        keep = ("name", "boardStatus", "priceStatus", "confirmed", "requiresCredits", "isFree", "layers", "pins",
                "ratsNest", "totalAirWires", "totalComponents", "creditsCostPerMinute", "warnings", "workflowStartedOn")
        out = {k: b.get(k) for k in keep}
        out["revisions"] = [{k: v for k, v in (rv or {}).items() if not isinstance(v, (dict, list)) or k in ("metrics",)}
                            for rv in (b.get("result") or {}).get("revisions", [])][-3:] if isinstance(b.get("result"), dict) else b.get("result")
        res["body"] = out
    return res


def download(board_id, revision, typ, out):
    r = requests.get(f"{BASE}/boards/{board_id}/revision-artifact", headers=H(), timeout=300,
                     params={"revision": revision, "type": typ})
    if r.ok:
        open(out, "wb").write(r.content)
        return {"http": r.status_code, "saved": out, "bytes": len(r.content)}
    return show(r)


def balance():
    return show(requests.get(f"{BASE}/apiuser/credit-flow", headers=H(), params={"PageSize": 5}, timeout=60))


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    fn = {"submit": submit, "confirm": confirm, "status": status, "download": download, "balance": balance}[cmd]
    print(json.dumps(fn(*args), indent=1, default=str)[:4000])
