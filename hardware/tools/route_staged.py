"""Staged autorouting through the EasyEDA bridge (stays under the API's 15-minute cap).

    python tools/route_staged.py board_b <windowId> [batch_size]

Routes non-BGA nets first, then BGA nets in batches, keeping earlier copper each time.
A batch that times out (no result) is split in half and retried. The PCB is saved after
every successful batch. Progress is appended to <board>/route_log.jsonl.
"""
import json
import sys
import time

from eda import execute

LAYERS = [1, 16, 19, 2]  # Top, In2, In5, Bottom (In1/In3/In4/In6 are planes)
CAP_S = 870


def run_batch(win, nets):
    start = ("globalThis.__ar = {state: 'running', started: Date.now()};"
             f"eda.pcb_Document.autoRouting({{RoutingNets: {json.dumps(nets)}, layers: {LAYERS}, ignoreNets: ['GND'],"
             " cornerStyle: 0, existingPrimitiveMode: 'keep', optimization: 1})"
             ".then(r => { globalThis.__ar = {state: 'done', ms: Date.now() - globalThis.__ar.started, result: r === undefined ? null : r}; })"
             ".catch(e => { globalThis.__ar = {state: 'error', error: String(e && (e.message || e))}; });"
             "return true;")
    r = execute(start, win)
    if not r.get("success"):
        return {"state": "error", "error": str(r)[:300]}
    t0 = time.time()
    while time.time() - t0 < CAP_S + 120:
        time.sleep(10)
        st = execute("return globalThis.__ar;", win).get("result")
        if isinstance(st, dict) and st.get("state") != "running":
            return st
    return {"state": "stuck"}


def counts(win):
    r = execute("const l = await eda.pcb_PrimitiveLine.getAllPrimitiveId(); const v = await eda.pcb_PrimitiveVia.getAllPrimitiveId();"
                " return [(l||[]).length, (v||[]).length];", win)
    return r.get("result")


def main():
    board, win = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    groups = json.load(open(f"{board}/route_groups.json"))
    queue = [("other", groups["other"])] + [(f"bga{i // size}", groups["bga"][i:i + size])
                                            for i in range(0, len(groups["bga"]), size)]
    log = open(f"{board}/route_log.jsonl", "a")
    failed = []
    while queue:
        name, nets = queue.pop(0)
        st = run_batch(win, nets)
        res = st.get("result") if isinstance(st, dict) else None
        rec = {"batch": name, "nets": len(nets), "state": st.get("state"), "ms": st.get("ms"),
               "ok": res and res.get("successNetsCount"), "total": res and res.get("totalNetsCount"),
               "failed": res and res.get("failedNets"), "copper": counts(win)}
        print(json.dumps(rec), flush=True)
        log.write(json.dumps(rec) + "\n")
        log.flush()
        if res:
            failed += res.get("failedNets") or []
            execute("return await eda.pcb_Document.save();", win)
        elif len(nets) > 1:
            h = len(nets) // 2
            queue[:0] = [(name + "a", nets[:h]), (name + "b", nets[h:])]
        else:
            failed += nets
    print(json.dumps({"done": board, "failed_nets": failed, "copper": counts(win)}), flush=True)


if __name__ == "__main__":
    main()
