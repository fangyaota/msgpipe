
import os, sys, json, subprocess, urllib.request, pathlib, re as _re

PROJ = pathlib.Path(__file__).resolve().parents[1]
TOKEN = (PROJ / "state" / "dsh" / "dida-token.txt").read_text(encoding="utf-8").strip()
URL = "https://mcp.dida365.com"
_sid = {"v": None}

def rpc(method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if _sid["v"]: req.add_header("Mcp-Session-Id", _sid["v"])
    ctx = ssl_ctx()
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        if r.headers.get("Mcp-Session-Id"): _sid["v"] = r.headers["Mcp-Session-Id"]
        raw = r.read().decode("utf-8", "replace")
    out = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("data:"): out.append(line[5:].strip())
    payload = "\n".join(out) if out else raw
    return json.loads(payload)

def ssl_ctx():
    import ssl
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def call(name, args):
    res = rpc("tools/call", {"name": name, "arguments": args})
    items = (res.get("result") or {}).get("content") or []
    txt = "".join(i.get("text", "") for i in items if i.get("type") == "text")
    try: return json.loads(txt)
    except Exception: return {"text": txt}
import sys, json, re

MARKERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
TIME_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
BR_RE = re.compile(r"^\[(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*([^:：]{1,24})[：:]\s*(.+)$")

def get_tasks():
    rpc("initialize", {"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"dsh","version":"1.0"}})
    rpc("notifications/initialized")
    res = rpc("tools/call", {"name":"filter_tasks","arguments":{"filter":{"status":[0]},"client_timezone":"Asia/Shanghai"}})
    return [json.loads(i["text"]) for i in (res.get("result") or {}).get("content",[]) if i.get("type")=="text"]

def split_blocks(sec):
    blocks, cur = [], None
    for l in [x.rstrip() for x in sec.split("\n")]:
        if l and l[0] in MARKERS:
            if cur: blocks.append(cur)
            cur = [l]
        else:
            if cur is None:
                if l.strip(): cur = [l]
            else: cur.append(l)
    if cur: blocks.append(cur)
    return ["\n".join(b).strip() for b in blocks if "\n".join(b).strip()]

def parse_header(h):
    """返回 (source, sender, time, remark) 或 (None,..) 表非消息块"""
    remark = ""
    m = re.search(r"[（(]([^（）()]*)[）)]\s*$", h)
    if m:
        remark, h = "（%s）" % m.group(1), h[:m.start()].strip()
    tm = TIME_RE.search(h)
    time = "%s %s" % (tm.group(1), tm.group(2)) if tm else ""
    rest = TIME_RE.sub("", h).strip(" ·-—")
    parts = [p.strip() for p in re.split(r"\s+[·・]\s+", rest) if p.strip()]
    if not time and len(parts) <= 1:
        return (rest or "未注明"), "", "", remark
    if time:
        source = parts[0] if parts else "未注明"
        sender = parts[1] if len(parts) > 1 else ""
    else:
        if len(parts) >= 3:   source, sender = parts[-2], parts[-1]
        elif len(parts) == 2: source, sender = parts[-1], ""
        elif len(parts) == 1: source, sender = parts[0], ""
        else:                 source, sender = "未注明", ""
    return source, sender, time, remark

def parse_block(b, prev_source):
    lines = [l for l in b.split("\n") if l.strip()]
    head, body_lines = lines[0], lines[1:]
    h = head[1:].strip() if head[0] in MARKERS else head.strip()
    # 非消息块：无时间、无分隔符、无 [时间] 人： 形态
    if not TIME_RE.search(h) and "·" not in h and not BR_RE.match(h) and not BR_RE.match("\n".join(body_lines)[:0]+h):
        has_branch = any(BR_RE.match(x.strip()) for x in body_lines)
        if not has_branch and not h.startswith("20"):
            return None, None, "非消息块"
    source, sender, time, remark = parse_header(h)
    branches, cur = [], None
    for l in body_lines:
        m = BR_RE.match(l.strip())
        if m:
            if cur: branches.append(cur)
            cur = {"time": m.group(1), "sender": m.group(2).strip(), "text": m.group(3).strip()}
        elif cur is not None:
            cur["text"] += " " + l.strip()
    if cur: branches.append(cur)
    if branches:
        return [{"source": source, "sender": br["sender"], "time": br["time"],
                 "remark": remark, "text": br["text"]} for br in branches], source, None
    body = "\n".join(body_lines).strip()
    if not body:
        return None, source, "块内无正文"
    if not (time or sender):
        # 允许「课件/附件/章节任务点」这类只有标题的块
        if not source or source == "未注明":
            return None, source, "无法解析来源"
    return [{"source": source, "sender": sender, "time": time, "remark": remark, "text": body}], source, None

def already_ok(c):
    if "【原始信息】" not in c: return False
    sec = c.split("【原始信息】", 1)[1].strip()
    blocks = [b for b in _re.split(r"\n\s*\n", sec) if b.strip()]
    if not blocks: return False
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        if not lines or lines[0][0] not in MARKERS: return False
        if len(lines) < 2 or not lines[1].strip().startswith("「"): return False
    return True

def norm(c):
    if "【原始信息】" not in c: return c, "无原始信息段"
    if already_ok(c): return c, "已统一"
    head, sec = c.split("【原始信息】", 1)
    out, prev, n = [], None, 0
    for b in split_blocks(sec):
        items, src, why = parse_block(b, prev)
        if why: return c, why
        if src: prev = src
        for it in items:
            n += 1
            mk = MARKERS[n-1] if n <= len(MARKERS) else f"{n}."
            hd = f"{mk} {it['source']}"
            if it["sender"]: hd += f" · {it['sender']}"
            if it["time"]:   hd += f" · {it['time']}"
            hd += it["remark"]
            txt = it["text"].strip()
            if not txt.startswith("「"): txt = "「" + txt.strip("「」") + "」"
            out.append(hd + "\n" + txt)
    if not out: return c, "无可规范化块"
    new = head.rstrip() + "\n\n【原始信息】\n" + "\n\n".join(out)
    return new, None

if __name__ == "__main__":
    ts = get_tasks()
    rows, meta = [], []
    for t in ts:
        old = t.get("content") or ""
        new, why = norm(old)
        st = "CHANGE" if why is None and new.strip() != old.strip() else ("SKIP " + str(why))
        print(f"[{st}] {t['title']}")
        if st == "CHANGE":
            meta.append({"id":t["id"],"title":t["title"],"etag":t.get("etag"),"old":old,"new":new})
    import tempfile
    outp = pathlib.Path(tempfile.gettempdir()) / "msgpipe_changes.json"
    json.dump(meta, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("will change:", len(meta))
