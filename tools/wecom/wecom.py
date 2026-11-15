#!/usr/bin/env python3
"""wecom-local —— 读本机企业微信本地消息库（wxSQLite3 解密 + 结构化输出）。

子命令：
  info                     环境与库状态（key 是否可用、解密了几个库、消息数）
  refresh [--force]        重新解密有变化的库（key 失效会报错并提示 scan-key）
  sessions [--since T]     会话列表（按最后消息时间倒序）
  messages [--since T]     消息流水（断点/会话过滤，--json 结构化）
  search 关键词 [--since]  全文搜正文
  history 会话             某会话的历史
  watch [--json]           只看断点之后的新消息，并推进断点（给 wechat-todo 用）
  watermark [--set T]      查看/设置断点
  key [--show]             查看 key（默认打码）
  set-key HEX              手动写入 key
  scan-key                 弹 UAC 抓 key（企业微信升级后 key 会变）
  media MSG_ID [--out DIR] 导出图片/文件到目录

时间参数接受 "2026-11-14 22:03" 或 "2026-11-14T22:03:00"。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import wxwork_crypto as wc  # noqa: E402
from protobuf_fields import ordered_fields  # noqa: E402

HOME = Path(os.environ.get("WECOM_LOCAL_HOME") or r"D:\Workspace\msgpipe\state\\wecom")
CACHE = HOME / "cache"
KEY_FILE = HOME / "key.txt"
STATE_FILE = HOME / "state.json"
WXWORK_ROOT = Path(os.environ.get("WECOM_DATA_ROOT") or (Path.home() / "Documents" / "WXWork"))
TZ = timezone(timedelta(hours=8))

TYPE_LABEL = {
    0: "文本", 2: "复合消息", 6: "文本",
    13: "文档链接", 14: "图片", 15: "文件", 16: "语音", 29: "表情", 40: "音视频通话",
    35: "链接", 38: "系统通知", 673: "引用/摘要", 1011: "事件", 1018: "通话事件", 2101: "事件",
    10: "卡片", 20: "卡片", 105: "卡片", 123: "卡片", 145: "卡片", 221: "卡片", 516: "卡片",
    561: "卡片", 565: "卡片", 570: "卡片", 573: "卡片", 579: "卡片", 580: "卡片", 581: "卡片", 582: "卡片",
}
CARD_TYPES = {10, 20, 105, 123, 145, 221, 516, 561, 565, 570, 573, 579, 580, 581, 582}


# ---------------------------------------------------------------- 基础设施

def die(msg: str, code: int = 1):
    print(f"!! {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    HOME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def accounts() -> list[Path]:
    if not WXWORK_ROOT.is_dir():
        return []
    return sorted(p for p in WXWORK_ROOT.iterdir() if (p / "Data").is_dir())


def acct_dbs(acct: Path) -> list[Path]:
    return sorted(p for p in (acct / "Data").glob("*.db"))


def load_key() -> bytes | None:
    if not KEY_FILE.exists():
        return None
    raw = KEY_FILE.read_text(encoding="utf-8").strip().splitlines()
    for line in raw:
        line = line.strip()
        if re.fullmatch(r"[0-9a-fA-F]{32}", line):
            return bytes.fromhex(line)
    return None


def save_key(hexkey: str):
    HOME.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(hexkey.strip().lower() + "\n", encoding="utf-8")
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass


def cache_path(acct: Path, db: Path) -> Path:
    return CACHE / acct.name / db.name


# ---------------------------------------------------------------- 解密刷新

def refresh(force: bool = False, quiet: bool = False) -> int:
    accts = accounts()
    if not accts:
        die(f"找不到企业微信数据目录：{WXWORK_ROOT}")
    key = load_key()
    if key is None:
        die("还没有 key。先跑：python wecom.py scan-key（会弹一次 UAC）")

    state = load_state()
    marks = state.setdefault("dbs", {})
    skips = set(state.get("skip", []))
    ok = bad = skipped = 0
    mismatched: list[str] = []
    for acct in accts:
        for db in acct_dbs(acct):
            st = db.stat()
            sig = f"{int(st.st_mtime)}:{st.st_size}"
            out = cache_path(acct, db)
            key_id = f"{acct.name}/{db.name}"
            if key_id in skips:
                skipped += 1
                continue
            if not force and marks.get(key_id) == sig and out.exists():
                skipped += 1
                continue
            try:
                wc.decrypt_database(db, out, key)
                marks[key_id] = sig
                ok += 1
            except ValueError as exc:
                msg = str(exc)
                marks.pop(key_id, None)
                bad += 1
                key_mismatch = "key validation failed" in msg
                if key_mismatch:
                    mismatched.append(key_id)
                    skips.add(key_id)
                if not quiet:
                    print(f".. 跳过 {key_id}: {msg}", file=sys.stderr)
    state["last_refresh"] = datetime.now(TZ).isoformat(timespec="seconds")
    state["skip"] = sorted(skips)
    save_state(state)
    if not quiet:
        print(f"refresh: 解密 {ok}，未变 {skipped}，失败 {bad}")
        for k in mismatched:
            print(f"   key 不匹配：{k}", file=sys.stderr)
    if not any(CACHE.rglob("message.db")):
        if mismatched:
            die("message.db 解不开 —— key 失效（企业微信可能升级过）。重跑：python wecom.py scan-key")
        die("没有解出 message.db，先跑 refresh --force")
    return ok


def ensure(offline: bool = False):
    if offline:
        return
    if not CACHE.exists() or not any(CACHE.rglob("message.db")):
        refresh(quiet=True)
        return
    # 有源库比缓存新就刷新
    for acct in accounts():
        for db in acct_dbs(acct):
            out = cache_path(acct, db)
            if not out.exists() or db.stat().st_mtime > out.stat().st_mtime:
                refresh(quiet=True)
                return


def find_db(name: str) -> Path | None:
    if not CACHE.is_dir():
        return None
    for p in sorted(CACHE.rglob(name)):
        return p
    return None


def connect(name: str) -> sqlite3.Connection:
    p = find_db(name)
    if p is None:
        die(f"缓存里没有 {name}，先跑 refresh")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_cols(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def first_table(con: sqlite3.Connection, *cands: str) -> str | None:
    names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    for c in cands:
        if c in names:
            return c
    for c in cands:
        for n in names:
            if n.startswith(c):
                return n
    return None


# ---------------------------------------------------------------- 名字解析

def conv_names() -> dict[str, str]:
    try:
        con = connect("session.db")
    except SystemExit:
        return {}
    try:
        t = first_table(con, "conversation_table", "conversation")
        if not t:
            return {}
        cols = table_cols(con, t)
        nk = "con_numeric_id" if "con_numeric_id" in cols else cols[0]
        ncol = "name" if "name" in cols else None
        icol = "id" if "id" in cols else None
        q = f"select {nk}, {ncol or 'NULL'}, {icol or 'NULL'} from {t}"
        out: dict[str, str] = {}
        for row in con.execute(q):
            nm = row[1] or row[2] or ""
            if not nm:
                continue
            out[str(row[0])] = nm
            if row[2]:
                out[str(row[2])] = nm
        return out
    finally:
        con.close()


def user_names() -> dict[int, str]:
    try:
        con = connect("user.db")
    except SystemExit:
        return {}
    try:
        t = first_table(con, "user_table", "user")
        if not t:
            return {}
        return {int(r[0]): (r[1] or "") for r in con.execute(f"select id, name from {t}")}
    finally:
        con.close()


# ---------------------------------------------------------------- 正文解析

def _try_text(b: bytes) -> str:
    try:
        s = b.decode("utf-8")
    except Exception:
        return ""
    if not s:
        return ""
    bad = sum(1 for ch in s if ord(ch) < 0x20 and ch not in "\n\t\r")
    if bad:
        return ""
    return s


def _clean(s: str) -> str:
    """去掉从 protobuf 里误带出来的单字节前缀（'9老师…'/'O 你的…' → 干净正文）。"""
    t = s.strip("\r\n\t ")
    changed = True
    while changed and len(t) > 1:
        changed = False
        if ord(t[0]) < 0x80:
            if t[1] == " " and len(t) > 2 and ord(t[2]) > 0x2E80:
                t = t[2:]
                changed = True
            elif ord(t[1]) > 0x2E80 or t[1] == "@":
                t = t[1:]
                changed = True
    return t


def _strings(raw: bytes, limit: int = 120) -> list[str]:
    out: list[str] = []

    def walk(b: bytes, depth: int = 0):
        if depth > 8 or len(out) > limit:
            return
        try:
            fs = ordered_fields(b)
        except Exception:
            return
        for _no, val in fs:
            if not isinstance(val, (bytes, bytearray)):
                continue
            s = _try_text(val)
            if s and len(s.strip()) >= 1:
                out.append(_clean(s))
            elif len(val) > 2:
                walk(val, depth + 1)

    walk(raw or b"")
    return out


def _card_title(raw: bytes) -> str:
    m = re.search(rb'"main_title"\s*:\s*\{[^}]*?"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw or b"")
    if m:
        try:
            return json.loads('"' + m.group(1).decode("utf-8", "ignore") + '"')
        except Exception:
            return m.group(1).decode("utf-8", "ignore")
    return ""


def render(ct: int, raw: bytes) -> str:
    ss = _strings(raw)
    texts = [s.strip() for s in ss if s.strip()]
    urls = [s for s in texts if s.startswith("http")]
    nonurl = [s for s in texts if not s.startswith("http")]

    if ct in (14, 15, 16):
        label = {14: "[图片]", 15: "[文件]", 16: "[语音]"}[ct]
        name = next((s for s in nonurl if re.search(r"\.\w{2,5}$", s)), "")
        return f"{label} {name}".strip()
    if ct == 13:
        title = next((s for s in nonurl if "/" not in s), "")
        return f"[文档] {title} {urls[0] if urls else ''}".strip()
    if ct == 35:
        title = nonurl[0] if nonurl else ""
        return f"[链接] {title} {urls[0] if urls else ''}".strip()
    if ct == 38:
        return f"[系统] {nonurl[0] if nonurl else ''}".strip()
    if ct in CARD_TYPES:
        t = _card_title(raw) or (nonurl[0] if nonurl else "")
        return f"[卡片] {t}".strip()
    best = max(texts, key=len) if texts else ""
    if not best and ct not in (0, 2, 6):
        return f"[type={ct}]"
    return best


def to_dt(ts: int) -> datetime:
    if ts > 10**11:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, TZ)


def parse_when(s: str) -> datetime:
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except ValueError:
        pass
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%m-%d %H:%M":
                dt = dt.replace(year=datetime.now(TZ).year)
            return dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    die(f"看不懂的时间：{s}")


# ---------------------------------------------------------------- 消息读取

def load_messages(since: datetime | None = None, conv: str | None = None, limit: int = 0) -> list[dict]:
    con = connect("message.db")
    try:
        t = first_table(con, "message_table", "message")
        if not t:
            die("message.db 里没有 message_table")
        cols = set(table_cols(con, t))
        want = ["message_id", "sender_id", "conversation_id", "content_type", "send_time", "content", "flag"]
        sel = [c for c in want if c in cols]
        rows = con.execute(f"select {', '.join(sel)} from {t}").fetchall()
    finally:
        con.close()

    convs = conv_names()
    users = user_names()
    out = []
    for r in rows:
        d = dict(r)
        dt = to_dt(int(d.get("send_time") or 0))
        if since and dt <= since:
            continue
        cid_raw = d.get("conversation_id")
        name = convs.get(str(cid_raw), "")
        if not name and str(cid_raw).isdigit():
            name = convs.get(str(int(cid_raw)), "")
        if not name:
            m = re.fullmatch(r"S:(\d+)_(\d+)", str(cid_raw))
            if m:
                name = users.get(int(m.group(1)), "") or users.get(int(m.group(2)), "")
        if not name:
            name = f"#{cid_raw}"
        if conv and conv.lower() not in name.lower():
            continue
        ct = int(d.get("content_type") or 0)
        out.append({
            "id": d.get("message_id"),
            "time": dt.isoformat(timespec="seconds"),
            "ts": int(dt.timestamp()),
            "conv": name,
            "sender": users.get(int(d.get("sender_id") or 0), "系统"),
            "type": ct,
            "type_label": TYPE_LABEL.get(ct, f"type{ct}"),
            "text": render(ct, d.get("content") or b""),
        })
    out.sort(key=lambda m: (m["ts"], str(m["id"])))
    if limit and limit > 0:
        out = out[-limit:]
    return out


def fmt_line(m: dict) -> str:
    t = datetime.fromisoformat(m["time"]).strftime("%Y-%m-%d %H:%M:%S")
    text = re.sub(r"\r?\n+", " ⏎ ", m["text"]).strip()
    return f"{t}\t{m['conv']}\t{m['sender']}\t{m['type_label']}\t{text}"


def print_msg(m: dict):
    print(fmt_line(m))


# ---------------------------------------------------------------- 子命令

def cmd_info(args):
    print(f"数据根  : {WXWORK_ROOT}")
    print(f"缓存    : {CACHE}")
    accts = accounts()
    print(f"账号    : {', '.join(a.name for a in accts) or '(未找到)'}")
    key = load_key()
    print(f"key     : {'已保存 ' + key.hex()[:8] + '…' if key else '缺失，需 scan-key'}")
    dbs = [p for p in CACHE.rglob("*.db")] if CACHE.is_dir() else []
    print(f"已解密  : {len(dbs)} 个库")
    state = load_state()
    print(f"上次刷新: {state.get('last_refresh', '(无)')}")
    wm = state.get("watermark_wecom", "")
    print(f"断点    : {wm or '(未设)'}")
    if find_db("message.db"):
        msgs = load_messages()
        print(f"消息    : {len(msgs)} 条 / {len({m['conv'] for m in msgs})} 个会话")
        if msgs:
            print(f"时间范围: {msgs[0]['time']} → {msgs[-1]['time']}")
    else:
        print("消息    : (还没有解密数据)")


def cmd_refresh(args):
    n = refresh(force=args.force)
    if find_db("message.db"):
        msgs = load_messages()
        print(f"共 {len(msgs)} 条消息 / {len({m['conv'] for m in msgs})} 个会话")


def cmd_sessions(args):
    ensure(args.offline)
    since = parse_when(args.since) if args.since else None
    msgs = load_messages(since=since)
    agg: dict[str, dict] = {}
    for m in msgs:
        a = agg.setdefault(m["conv"], {"conv": m["conv"], "count": 0, "first": m["time"], "last": m["time"]})
        a["count"] += 1
        a["first"] = min(a["first"], m["time"])
        a["last"] = max(a["last"], m["time"])
    items = sorted(agg.values(), key=lambda x: x["last"], reverse=True)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    for a in items:
        print(f"{a['last'][:16]}\t{a['count']:>4} 条\t{a['conv']}\t(最早 {a['first'][:10]})")
    print(f"-- {len(items)} 个会话，{sum(a['count'] for a in items)} 条消息")


def cmd_messages(args):
    ensure(args.offline)
    since = parse_when(args.since) if args.since else None
    msgs = load_messages(since=since, conv=args.conv, limit=args.limit)
    if args.json:
        print(json.dumps(msgs, ensure_ascii=False, indent=2))
        return
    for m in msgs:
        print_msg(m)


def cmd_search(args):
    ensure(args.offline)
    since = parse_when(args.since) if args.since else None
    kw = args.query.lower()
    msgs = [m for m in load_messages(since=since) if kw in m["text"].lower() or kw in m["conv"].lower()]
    if args.limit:
        msgs = msgs[::-1][: args.limit][::-1]
    if args.json:
        print(json.dumps(msgs, ensure_ascii=False, indent=2))
        return
    for m in msgs:
        print_msg(m)
    print(f"-- {len(msgs)} 条命中")


def cmd_history(args):
    args.conv = args.conv
    cmd_messages(argparse.Namespace(since=args.since, conv=args.conv, limit=args.limit,
                                    json=args.json, offline=args.offline))


def cmd_watch(args):
    ensure(args.offline)
    state = load_state()
    wm = state.get("watermark_wecom") or ""
    since = parse_when(wm) if wm else None
    msgs = load_messages(since=since)
    if args.json:
        print(json.dumps({"since": wm, "messages": msgs}, ensure_ascii=False, indent=2))
    else:
        for m in msgs:
            print_msg(m)
        print(f"-- 断点之后 {len(msgs)} 条（断点 {wm or '无'}）")
    if msgs and not args.no_advance:
        state["watermark_wecom"] = msgs[-1]["time"]
        save_state(state)


def cmd_watermark(args):
    state = load_state()
    if args.set is not None:
        dt = parse_when(args.set) if args.set else ""
        state["watermark_wecom"] = dt.isoformat(timespec="seconds") if dt else ""
        save_state(state)
    print(state.get("watermark_wecom") or "(未设)")


def cmd_key(args):
    key = load_key()
    if not key:
        die("还没有 key，跑 scan-key")
    print(key.hex() if args.show else key.hex()[:8] + "…" + key.hex()[-4:])


def cmd_set_key(args):
    if not re.fullmatch(r"[0-9a-fA-F]{32}", args.hex.strip()):
        die("key 必须 32 位十六进制")
    save_key(args.hex)
    print("已保存 key")


def cmd_scan_key(args):
    dbs = [p for a in accounts() for p in acct_dbs(a) if p.name == "message.db"]
    if not dbs:
        die("找不到 message.db，无法校验 key")
    out = HOME / "key-find.txt"
    bat = HERE / "run_find_key.bat"
    py = sys.executable
    bat.write_text(
        "@echo off\r\n"
        f'"{py}" "{HERE / "find_key.py"}" --out "{out}" > "{HOME / "find_key.log"}" 2>&1\r\n',
        encoding="ascii",
    )
    HOME.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    print("弹 UAC 授权（扫 WXWork.exe 内存找 key）…")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Start-Process -FilePath '{bat}' -Verb RunAs -WindowStyle Hidden -Wait"],
        check=False,
    )
    if not out.exists():
        die(f"没抓到 key，看日志：{HOME / 'find_key.log'}")
    keys = [l.strip() for l in out.read_text(encoding="utf-8").splitlines() if re.fullmatch(r"[0-9a-f]{32}", l.strip())]
    if not keys:
        die("日志里没有有效 key")
    save_key(keys[0])
    print(f"抓到 key：{keys[0][:8]}…，共 {len(keys)} 个候选")
    refresh(force=True)


def cmd_media(args):
    ensure(args.offline)
    con = connect("message.db")
    try:
        t = first_table(con, "message_table")
        cols = set(table_cols(con, t))
        if "message_id" not in cols:
            die("message_table 缺 message_id")
        row = con.execute(
            f"select content_type, content from {t} where message_id = ?", (args.id,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        die(f"没有 message_id={args.id}")
    ct, raw = int(row[0]), row[1]
    ss = [s.strip() for s in _strings(raw) if s.strip()]
    name = next((s for s in ss if re.search(r"\.\w{2,5}$", s)), "")
    if not name:
        die(f"这条 type={ct} 没有文件名，无法定位原件")
    dest = Path(args.out or (HOME / "media"))
    dest.mkdir(parents=True, exist_ok=True)
    hits = []
    for acct in accounts():
        for sub in ("Cache/File", "Cache/Image", "Cache/Emotion", "Cache/Video"):
            base = acct / sub
            if not base.is_dir():
                continue
            for p in base.rglob(name):
                if p.is_file():
                    hits.append(p)
                    break
    if not hits:
        die(f"Cache 里没找到 {name}")
    for src in hits:
        target = dest / (src.name if len(hits) == 1 else f"{src.parent.parent.name}_{src.name}")
        shutil.copy2(src, target)
        print(f"导出 {target}  ({src.stat().st_size} B)")


# ---------------------------------------------------------------- 入口

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wecom.py", description="企业微信本地消息库读取器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info"); p.set_defaults(func=cmd_info)
    p = sub.add_parser("refresh"); p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_refresh)

    def add_common(p):
        p.add_argument("--offline", action="store_true", help="不刷新，直接读缓存")
        p.add_argument("--json", action="store_true", help="JSON 输出")

    p = sub.add_parser("sessions"); add_common(p)
    p.add_argument("--since"); p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("messages"); add_common(p)
    p.add_argument("--since"); p.add_argument("--conv"); p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_messages)

    p = sub.add_parser("search"); add_common(p)
    p.add_argument("query"); p.add_argument("--since"); p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("history"); add_common(p)
    p.add_argument("conv"); p.add_argument("--since"); p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("watch"); add_common(p)
    p.add_argument("--no-advance", action="store_true"); p.set_defaults(func=cmd_watch)

    p = sub.add_parser("watermark"); p.add_argument("--set"); p.set_defaults(func=cmd_watermark)

    p = sub.add_parser("key"); p.add_argument("--show", action="store_true"); p.set_defaults(func=cmd_key)
    p = sub.add_parser("set-key"); p.add_argument("hex"); p.set_defaults(func=cmd_set_key)
    p = sub.add_parser("scan-key"); p.set_defaults(func=cmd_scan_key)

    p = sub.add_parser("media"); add_common(p)
    p.add_argument("id", type=int); p.add_argument("--out"); p.set_defaults(func=cmd_media)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        pass
