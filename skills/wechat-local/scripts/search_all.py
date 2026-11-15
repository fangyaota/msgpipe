# -*- coding: utf-8 -*-
"""微信全量关键词检索（含 zstd 压缩消息，补上 wxcli search 的盲区）

用法:
  python search_all.py <关键词> [--context N] [--chat 显示名或username] [--limit N] [--dbg]

输出: >> 命中行 / 空格缩进行为上下文
前置: 解密缓存存在；若报缓存缺失，先跑一条 wxcli 命令（如 sessions）触发解密。

2026-11 修复：_mtimes.json 的 rel_key 是**单反斜杠**（message\\message_0.db 的 JSON 里
写作 "message\\\\message_0.db"），旧代码用 r"message\\\\message_0.db" 常量去比，永远匹配
不上，于是所有关键词都命中 0；另外消息库按 message_0/_1/_2 分片，旧代码只读 _0 和
biz_message_0，漏掉大部分会话。现在改为：键归一化 + 缓存目录里凡带 Msg_ 表的库全部纳入，
并兼容 compress_content 列。
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

SENDER_PREFIX = re.compile(r"^(?:wxid_[A-Za-z0-9_]+|gh_[A-Za-z0-9_]+):\s*\n?")

CACHE = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".", "wechat_cli_cache")


def load_zstd():
    for p in (os.path.join(os.environ.get("LOCALAPPDATA") or "", "Temp",
                           "wechat-cli-plus-pydeps"),
              os.path.join(os.path.expanduser("~"), ".wechat-cli", "deps")):
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    import zstandard as zstd
    return zstd


def norm_key(rel):
    """统一成单反斜杠：message\\message_0.db"""
    k = rel.replace("/", "\\")
    while "\\\\" in k:
        k = k.replace("\\\\", "\\")
    return k


def cache_map():
    """rel_key(归一化) -> 解密后的 .db 路径"""
    out = {}
    mt = os.path.join(CACHE, "_mtimes.json")
    if os.path.isfile(mt):
        try:
            with open(mt, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {}
        for k, v in info.items():
            p = v.get("path") if isinstance(v, dict) else v
            if p and os.path.isfile(p):
                out[norm_key(k)] = p
    return out


def has_msg_tables(path):
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            return con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'Msg_%'").fetchone()[0]
    except sqlite3.Error:
        return 0


def message_dbs(mapping):
    """所有带 Msg_ 表的解密库（message_0/_1/_2 分片 + biz），按路径去重"""
    cands = [p for k, p in mapping.items() if k.startswith("message\\")]
    if os.path.isdir(CACHE):
        for f in sorted(os.listdir(CACHE)):
            if f.endswith(".db"):
                cands.append(os.path.join(CACHE, f))
    seen, out = set(), []
    for p in cands:
        if p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        if has_msg_tables(p):
            out.append(p)
    return out


def find_contact_db(mapping):
    p = mapping.get("contact\\contact.db")
    if p and os.path.isfile(p):
        return p
    for k, v in mapping.items():
        if k.endswith("contact.db") and os.path.isfile(v):
            return v
    return None


def display_names(mapping):
    """username -> 显示名（备注优先），来自解密的 contact.db"""
    names = {}
    p = find_contact_db(mapping)
    if not p:
        return names
    try:
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as con:
            for un, remark, nick in con.execute(
                    "SELECT username, remark, nick_name FROM contact"):
                if un:
                    names[un] = remark or nick or un
    except sqlite3.Error:
        pass
    return names


def table_owner_map(con):
    """Msg_<md5(username)> 表名 -> (表映射, rowid->username)"""
    mapping, rowid_map = {}, {}
    try:
        rows = con.execute("SELECT rowid, user_name FROM Name2Id").fetchall()
    except sqlite3.Error:
        return mapping, rowid_map
    for rid, un in rows:
        if un:
            rowid_map[rid] = un
            mapping["Msg_" + hashlib.md5(un.encode()).hexdigest()] = un
    return mapping, rowid_map


def dec(mc, ct, dctx):
    if mc is None:
        return ""
    if isinstance(mc, bytes):
        if ct == 4:
            try:
                return dctx.decompress(mc).decode("utf-8", errors="replace")
            except Exception:
                pass
        else:
            try:
                return mc.decode("utf-8")
            except UnicodeDecodeError:
                pass
        try:
            return dctx.decompress(mc).decode("utf-8", errors="replace")
        except Exception:
            return mc.decode("utf-8", errors="replace")
    return str(mc)


def row_text(row, cols, dctx):
    """按列名拼出可搜文本（message_content + compress_content）"""
    txt = dec(row[cols["message_content"]], row[cols["message_content_ct"]], dctx)
    if "compress_content" in cols:
        ct = row[cols["compress_content_ct"]] if "compress_content_ct" in cols else None
        txt += dec(row[cols["compress_content"]], ct, dctx)
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword")
    ap.add_argument("--context", type=int, default=0, help="附带前后N条消息")
    ap.add_argument("--chat", default=None, help="限定会话（显示名或username）")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dbg", action="store_true", help="打印用到的库/表统计")
    args = ap.parse_args()

    zstd = load_zstd()
    dctx = zstd.ZstdDecompressor()
    mapping = cache_map()
    dbs = message_dbs(mapping)
    if not dbs:
        print("解密缓存缺失：先运行一次 ~/.wechat-cli/wxcli.cmd sessions",
              file=sys.stderr)
        sys.exit(1)

    names = display_names(mapping)
    hits = 0
    scanned = 0

    for path in dbs:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            owners, rowids = table_owner_map(con)
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'Msg_%'")]
            for t in tables:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info([{t}])")]
                if "message_content" not in cols:
                    continue
                owner = owners.get(t, "")
                disp = names.get(owner, owner) or owner
                if not disp:
                    disp = t
                if args.chat and args.chat not in (disp, owner):
                    continue
                fields = ["local_id", "local_type", "create_time", "real_sender_id",
                          "message_content", "WCDB_CT_message_content"]
                idx = {"local_id": 0, "local_type": 1, "create_time": 2,
                       "real_sender_id": 3, "message_content": 4,
                       "message_content_ct": 5}
                if "compress_content" in cols:
                    fields.append("compress_content")
                    idx["compress_content"] = len(fields) - 1
                    if "WCDB_CT_compress_content" in cols:
                        fields.append("WCDB_CT_compress_content")
                        idx["compress_content_ct"] = len(fields) - 1
                try:
                    rows = con.execute(
                        f"SELECT {', '.join(fields)} FROM [{t}] ORDER BY local_id"
                    ).fetchall()
                except sqlite3.Error:
                    continue
                scanned += len(rows)
                texts = [row_text(r, idx, dctx) for r in rows]
                for i, s in enumerate(texts):
                    if args.keyword not in s:
                        continue
                    if hits >= args.limit:
                        break
                    lo = max(0, i - args.context)
                    hi = min(len(rows), i + args.context + 1)
                    for j in range(lo, hi):
                        lid, _lt, ts, sid = rows[j][:4]
                        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                        sender_un = rowids.get(sid, "")
                        sender = names.get(sender_un, sender_un) or "?"
                        body = SENDER_PREFIX.sub("", texts[j]).replace("\n", " ")[:200]
                        marker = ">>" if j == i else "  "
                        print(f"{marker} [{when}] {disp} | {sender}: {body}")
                    if args.context:
                        print("-" * 60)
                    hits += 1
                if hits >= args.limit:
                    break
        if hits >= args.limit:
            break
    if args.dbg:
        print(f"[dbg] 库 {len(dbs)} 个，扫描消息 {scanned} 条", file=sys.stderr)
    print(f"共 {hits} 条命中", file=sys.stderr)


if __name__ == "__main__":
    main()
