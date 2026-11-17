# -*- coding: utf-8 -*-
"""msgscan —— 微信 / 企业微信 / 学习通 三线统一门面

把三套完全不同的接口归一成同样的动作与同样的输出列：

  time | source | conv | sender | text

动作：
  sources                     三线可用性自检
  sessions [--since AT]       各会话条数与最后时间
  since --at AT               断点之后的消息（AT 省略则用状态文件里的水位）
  search KW [--since AT]      关键词检索
  assignments [--refresh]     学习通作业/试卷（表格输出，列不同）
  advance --at AT             把水位推进到 AT

通用参数：--source wechat,wecom / --limit N / --json
状态文件：D:/Workspace/msgpipe/state/msgscan.json  {"watermark_wechat": iso, "watermark_wecom": iso}
"""
import argparse
import io
import json
import os
import subprocess
import time
import shutil
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(PROJ, "state")
STATE = os.path.join(STATE_DIR, "msgscan.json")
WECHAT_SCRIPTS = os.path.join(HOME, ".dsh", "skills", "wechat-local", "scripts")
WECOM_SCRIPTS = os.path.join(PROJ, "tools", "wecom")
PY = os.environ.get("MSGPIPE_PY") or sys.executable
XXT_REPORT = os.path.join(PROJ, "tools", "xxt", "courses_report.json")
XXT_SCAN = os.path.join(PROJ, "tools", "xxt", "scan_all.py")
XXT_VENV = os.path.join(PROJ, "tools", "xxt", "chaoxing-agent-cli-main", ".venv", "Scripts", "python.exe")
XXT_PY = XXT_VENV if os.path.isfile(XXT_VENV) else None
CXMCP_DIR = os.path.join(PROJ, "tools", "cxmcp")
CXMCP_DUMP = os.path.join(CXMCP_DIR, "dump.mjs")
CXMCP_INDEX = os.path.join(CXMCP_DIR, "messages", "_index.json")


# ---------------------------------------------------------------- 状态
def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def parse_at(s, default=None):
    if not s:
        return default
    try:  # 兼容 state.json 里的 ISO 带时区写法
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise SystemExit(f"时间格式无法解析：{s}（用 2026-11-15 14:57 这种）")


# ---------------------------------------------------------------- 微信
_WX_SYNCED = [False]


def _wx_sync_cache():
    """让 wxcli 自己把新数据同步进解密缓存（0.2 秒，无命中搜索即可触发）。"""
    if _WX_SYNCED[0] or os.environ.get("MSGPIPE_NO_WX_SYNC"):
        return
    _WX_SYNCED[0] = True
    cmd = os.path.join(os.environ.get("USERPROFILE", ""), ".wechat-cli", "wxcli.cmd")
    if not os.path.isfile(cmd):
        return
    try:
        subprocess.run([cmd, "search", "zzz_no_such_keyword"], capture_output=True, timeout=60)
    except Exception:
        pass


def wechat_rows(cutoff=None, limit=None):
    """返回 [(datetime, conv, sender, text)]，按时间升序"""
    if not os.path.isdir(WECHAT_SCRIPTS):
        raise SystemExit("微信线没装：先跑 scripts\\install-skills.cmd 装 wechat-local 技能")
    sys.path.insert(0, WECHAT_SCRIPTS)
    import sqlite3
    try:
        import search_all as S  # noqa: E402
    except ModuleNotFoundError as e:
        raise SystemExit(f"微信线依赖缺失（{e}）：重跑 scripts\\install-skills.cmd")
    _wx_sync_cache()

    try:
        zstd = S.load_zstd()
    except Exception as e:  # pragma: no cover
        raise SystemExit(f"zstandard 不可用：{e}")
    dctx = zstd.ZstdDecompressor()
    mapping = S.cache_map()
    dbs = S.message_dbs(mapping)
    if not dbs:
        raise SystemExit("微信解密缓存缺失：先跑一次 ~/.wechat-cli/wxcli.cmd sessions")
    names = S.display_names(mapping)

    out = []
    for path in dbs:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            owners, rowids = S.table_owner_map(con)
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
            for t in tables:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info([{t}])")]
                if "message_content" not in cols or "create_time" not in cols:
                    continue
                owner = owners.get(t, "")
                disp = names.get(owner, owner) or t
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
                        f"SELECT {', '.join(fields)} FROM [{t}] ORDER BY local_id").fetchall()
                except sqlite3.Error:
                    continue
                for r in rows:
                    ts = r[2]
                    if not ts:
                        continue
                    try:
                        when = datetime.fromtimestamp(ts)
                    except (OSError, ValueError):
                        continue
                    if cutoff and when < cutoff:
                        continue
                    body = S.SENDER_PREFIX.sub("", S.row_text(r, idx, dctx))
                    body = body.replace("\r", " ").replace("\n", " ").strip()
                    if not body:
                        continue
                    sid = r[3]
                    s_un = rowids.get(sid, "")
                    sender = names.get(s_un, s_un) or s_un or ""
                    out.append((when, disp, sender, body))
    out.sort(key=lambda x: x[0])
    if limit:
        out = out[-limit:]
    return out


# ---------------------------------------------------------------- 企业微信
def wecom_rows(cutoff=None, limit=None):
    script = os.path.join(WECOM_SCRIPTS, "wecom.py")
    if not os.path.isfile(script):
        raise SystemExit(f"找不到 wecom.py：{script}")
    env = {**os.environ,
           "WECOM_LOCAL_HOME": os.path.join(PROJ, "state", "wecom"),
           "PYTHONIOENCODING": "utf-8"}
    # 企微线读的是解密缓存，而 WXWork 的库会一直变；不先 refresh 就会一直读到旧缓存。
    if not os.environ.get("MSGPIPE_NO_WECOM_SYNC"):
        r = subprocess.run([PY, script, "refresh"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=180)
        if r.returncode != 0:
            print(f"[企微] refresh 失败，继续用旧缓存："
                  f"{(r.stderr or r.stdout).strip()[:200]}", file=sys.stderr)
    cmd = [PY, script, "messages", "--offline", "--json", "--limit",
           str(limit or 5000)]
    if cutoff:
        cmd += ["--since", cutoff.strftime("%Y-%m-%d %H:%M:%S")]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace",
                       env=env)
    if p.returncode != 0:
        raise SystemExit(f"企业微信读取失败：{(p.stderr or p.stdout).strip()[:300]}")
    try:
        data = json.loads(p.stdout.strip() or "[]")
    except json.JSONDecodeError:
        raise SystemExit(f"企业微信输出不是 JSON：{p.stdout[:200]}")
    out = []
    for m in data:
        try:
            when = datetime.fromisoformat(m["time"]).replace(tzinfo=None)
        except Exception:
            when = datetime.fromtimestamp(m.get("ts", 0))
        text = (m.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
        if not text:
            continue
        out.append((when, m.get("conv", ""), m.get("sender", ""), text))
    if cutoff:
        out = [r for r in out if r[0] >= cutoff]
    old = cutoff is not None
    if limit and not old:
        out = out[-limit:]
    return out


# ---------------------------------------------------------------- 学习通
def chaoxing_rows(cutoff=None, limit=None):
    """学习通 IM 消息（课程群聊）。走 _cxmcp 的 dump.mjs，按 syncTtlSeconds 增量。"""
    if not os.path.isfile(CXMCP_DUMP):
        raise SystemExit("学习通消息线未安装：缺 tools/cxmcp/dump.mjs（先在 tools/cxmcp 里 npm install，见 README 第 6 步）")
    node = shutil.which("node") or "C:/Program Files/nodejs/node.exe"
    if not os.path.exists(CXMCP_DUMP):
        raise SystemExit(f"没有 {CXMCP_DUMP}")
    args = [node, CXMCP_DUMP]
    if cutoff:
        args += ["--since", cutoff.strftime("%Y-%m-%d %H:%M:%S")]
    if limit:
        args += ["--limit", str(max(limit * 4, 200))]
    proc = subprocess.run(args, cwd=CXMCP_DIR, capture_output=True, timeout=300,
                            stdin=subprocess.DEVNULL)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if not out:
        raw = proc.stderr.decode("utf-8", "replace")
        if "Cannot find module" in raw or "ERR_MODULE_NOT_FOUND" in raw:
            raise SystemExit("学习通消息线依赖没装：在 tools/cxmcp 里跑 npm install"
                             "（README 第 6 步），再跑 seed-cxmcp.cmd 准备登录态")
        if "not logged in" in raw.lower() or "登录" in raw:
            raise SystemExit("学习通消息线未登录：跑 scripts\\seed-cxmcp.cmd 登录一次")
        err = raw.strip().splitlines()[-3:]
        raise SystemExit(" / ".join(err) or f"退出码 {proc.returncode}")
    rows = []
    for item in json.loads(out):
        try:
            when = datetime.strptime(item["time"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, KeyError):
            continue
        rows.append((when, item.get("conv", ""), item.get("sender", ""), item.get("text", "")))
    return rows


def xxt_assignments(refresh=False):
    if refresh:
        if not os.path.isfile(XXT_SCAN):
            raise SystemExit(f"找不到巡检脚本：{XXT_SCAN}")
        print("[msgscan] 正在巡检学习通 14 门课，约 1-2 分钟…", file=sys.stderr)
        p = subprocess.run([XXT_PY or PY, XXT_SCAN], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env={**os.environ,
                                "TEMP": os.path.join(PROJ, "state", "xxt", "tmp"),
                                "TMP": os.path.join(PROJ, "state", "xxt", "tmp"),
                                "PLAYWRIGHT_BROWSERS_PATH": os.path.join(PROJ, "tools", "xxt", "browsers"),
                                "XXT_STATE_DIR": os.path.join(PROJ, "state", "xxt"),
                                "PYTHONIOENCODING": "utf-8"})
        if p.returncode != 0:
            raise SystemExit(f"学习通巡检失败：{(p.stderr or p.stdout).strip()[:300]}")
    if not os.path.isfile(XXT_REPORT):
        raise SystemExit(f"还没有巡检结果，先跑：msgscan assignments --refresh")
    with open(XXT_REPORT, encoding="utf-8") as f:
        rep = json.load(f)
    rows = []
    courses = rep if isinstance(rep, list) else (rep.get("courses") or [])
    if courses and all(c.get("error") for c in courses):
        raise SystemExit("学习通登录态失效（14 门课全部 AUTH_REQUIRED）："
                         "跑 tools\\xxt\\xxt.cmd auth --headed 扫一次码，再 assignments --refresh")
    for c in courses:
        cname = c.get("title") or c.get("course") or c.get("name") or ""
        for h in c.get("detail") or c.get("homeworks") or []:
            status = h.get("status") or ""
            title = (h.get("name") or h.get("title") or "").replace("\n", " ")
            extra = (h.get("time") or "").strip()
            rows.append((status, cname, title, extra))
    rows.sort(key=lambda r: ({"未交": 0, "待批阅": 1}.get(r[0], 2), r[1]))
    return rows


CHATROOM_PREFIX = __import__("re").compile(r"^[A-Za-z0-9_@.\-]+@chatroom:\s*")


def clean_rows(rows, width=300):
    """默认去掉纯系统消息与过长的刷屏，并截断正文"""
    keep = []
    for w, src, conv, sd, t in rows:
        t = CHATROOM_PREFIX.sub("", t)
        low = t.lstrip()
        if low.startswith("<sysmsg") or low.startswith("<msg"):
            continue
        if low.startswith("[type=") and low.endswith("]"):
            continue
        t = t if len(t) <= width else t[:width] + "…"
        keep.append((w, src, conv, sd, t))
    return keep


# ---------------------------------------------------------------- 数你最灵（浏览器）
BSK = os.path.join(os.environ.get("LOCALAPPDATA", ""), "BrowserSkill", "bin", "bsk.exe")
SX_URL = "https://smartestu.cn/assignment"
MUC_URL = "http://my.muc.edu.cn/page/11#/"
MUC_API = "/comsys-portal-notice-web/getNoticeByPage"
MUC_JS = r"""
(async ([api, pages, kw]) => {
  const out = []; const seen = new Set();
  for (let p = 1; p <= pages; p++) {
    const f = new URLSearchParams({currentPage: String(p), pageSize: '15',
      searchValue: kw || '', state: '', is_add: '0', totalCounts: '13', total: '-1',
      select_all: 'false', select_notice: '', type: '', searchDepartment: '',
      start_date: '', end_date: '', system_show: '1'});
    const r = await fetch(api, {method:'POST',
      headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
               'X-Requested-With':'XMLHttpRequest',
               'Accept':'application/json, text/plain, */*'},
      body: f.toString(), credentials:'include'});
    const t = await r.text();
    let j; try { j = JSON.parse(t); } catch (e) { return JSON.stringify({error:'not-json', sample: t.slice(0,120)}); }
    const rows = (j.datas && j.datas.tables) || [];
    if (!rows.length) break;
    for (const x of rows) {
      const id = x.notice_id || x.notice_title;
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({time: x.notice_release_time || x.notice_first_time || '',
        type: x.notice_type_name || '', dept: x.organization_name || '',
        title: x.notice_title || '', link: x.notice_link || '', id: x.notice_id || ''});
    }
  }
  return JSON.stringify({rows: out});
})([API, PAGES, KEYWORD])
"""
SX_JS = (r"JSON.stringify(Array.from(document.querySelectorAll('table tbody tr'))"
         r".map(tr=>Array.from(tr.cells).map(td=>td.innerText.trim().replace(/\s+/g,' '))))")
SX_COUNT_JS = "document.querySelectorAll('table tbody tr').length"
SX_SCRIPT = os.path.join(PROJ, "scripts", "smartestu_assignments.py")
SX_CMD = os.path.join(PROJ, "scripts", "smartestu.cmd")
SX_PROFILE = os.path.join(PROJ, "state", "smartestu", "profile")


def _bsk(*args, timeout=90):
    p = subprocess.run([BSK, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def _bsk_bootstrap():
    """bsk 守护进程空闲 600 秒会自己退出。在任务里 `bsk status` 想自动拉起会失败
    （Job Object 限制，os error 5），这里用 DETACHED_PROCESS 起一个真正脱离的守护进程。"""
    if not os.path.isfile(BSK):
        return False
    print("[bsk] 守护进程没在跑，后台拉起一个", file=sys.stderr)
    env = dict(os.environ, BSK_AUTO_START="0")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    try:
        subprocess.Popen([BSK, "daemon", "start", "--foreground"], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except Exception as exc:
        print(f"[bsk] 拉起失败：{exc}", file=sys.stderr)
        return False
    for _ in range(10):
        time.sleep(0.6)
        rc, out, err = _bsk("status", "--json", timeout=15)
        if rc == 0 and '"pid"' in (out or ""):
            return True
    return False


def _bsk_json(*args, timeout=90):
    rc, out, err = _bsk(*args, timeout=timeout)
    if rc != 0 and ("daemon" in (err or "") + (out or "") or rc == 2):
        _bsk_bootstrap()
        rc, out, err = _bsk(*args, timeout=timeout)
    txt = (out or "").strip()
    for cand in (txt, txt[txt.index("{"):] if "{" in txt else "", txt[txt.index("["):] if "[" in txt else ""):
        if not cand:
            continue
        try:
            return json.loads(cand)
        except Exception:
            continue
    raise SystemExit(f"bsk {' '.join(args[:2])} 失败：{(err or out).strip()[:300]}")


def _smartestu_playwright():
    """读数你最灵作业表（独立 Playwright profile，不需要 browser-skill）。"""
    if not os.path.isfile(SX_SCRIPT):
        raise SystemExit(f"缺脚本：{SX_SCRIPT}")
    py = os.environ.get("MSGPIPE_PY")
    if not py or not os.path.isfile(py):
        cand = os.path.join(PROJ, "tools", "xxt", "chaoxing-agent-cli-main", ".venv",
                            "Scripts", "python.exe")
        py = cand if os.path.isfile(cand) else sys.executable
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               TEMP=os.path.join(PROJ, "state", "xxt", "tmp"),
               TMP=os.path.join(PROJ, "state", "xxt", "tmp"),
               PLAYWRIGHT_BROWSERS_PATH=os.path.join(PROJ, "tools", "xxt", "browsers"))
    p = subprocess.run([py, SX_SCRIPT], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300,
                       env=env, stdin=subprocess.DEVNULL)
    if p.returncode == 3:
        raise SystemExit("数你最灵未登录：先跑 scripts\\smartestu.cmd --login")
    if p.returncode != 0:
        raise SystemExit((p.stderr or p.stdout).strip()[:300])
    try:
        raw = json.loads(p.stdout[p.stdout.index("["):])
    except Exception:
        raise SystemExit("数你最灵返回内容无法解析")
    import re as _re
    out = []
    for cells in raw:
        if len(cells) < 4:
            continue
        course, name, span, status = cells[0], cells[1], cells[2], cells[3]
        m = _re.search(r"结束时间\s*(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})", span)
        due = f"{m.group(1)} {m.group(2)}" if m else ""
        stat = "未交" if ("未提交" in status or "未完成" in status) else "已完成"
        out.append((stat, course, name, " ".join(x for x in (due, status) if x)[:120]))
    out.sort(key=lambda r: (r[0] != "未交", r[3]))
    return out


def smartestu_assignments():
    """数你最灵派发：先试 browser-skill（复用已登录的 Edge），不行再用独立 Playwright profile。"""
    first = None
    if os.path.isfile(BSK):
        try:
            return _smartestu_bsk()
        except SystemExit as e:
            first = e
    try:
        return _smartestu_playwright()
    except SystemExit as e:
        raise SystemExit(f"{e}" + (f"（bsk 也失败：{first}）" if first else ""))


def _smartestu_bsk():
    """读数你最灵作业表（browser-skill 路线）。用浏览器里已登录的会话，不新建登录。

    用户 2026-11-15 定：既然已自动化，每轮都查（不再等公众号新消息）。

    窗口用 --focus 前台打开（用户 2026-11-15 定：要看得见我在干什么），
    读完若会话是本次新建的就立刻关掉，不留后台窗口。
    """
    if not os.path.isfile(BSK):
        raise SystemExit(f"找不到 bsk.exe：{BSK}")
    st = _bsk_json("status", "--json")
    browsers = st.get("browsers") or []
    if not browsers:
        raise SystemExit("没有连上浏览器：先在浏览器里启用 browser-skill 扩展")
    bid = browsers[0]["instance_id"]
    sessions = _bsk_json("session", "list", "--json") or []
    created = False
    if sessions:
        sid = sessions[0]["session_id"]
    else:
        s = _bsk_json("session", "start", "--browser", bid, "--focus", "--json")
        sid = s.get("session_id")
        created = True
    try:
        _bsk("navigate", "--session", sid, SX_URL)
        import time as _t
        for _ in range(20):          # 等表格渲染出来（SPA 拉完数据才有行）
            rc, out, _err = _bsk("evaluate", "--session", sid, "--json", SX_COUNT_JS)
            try:
                n = int(json.loads(out[out.index("{"):]).get("value") or 0)
            except Exception:
                n = 0
            if n:
                break
            _t.sleep(1.5)
        rc, out, err = _bsk("evaluate", "--session", sid, "--json", SX_JS)
        if rc != 0:
            raise SystemExit(f"读取失败：{(err or out).strip()[:300]}")
        val = json.loads(out[out.index("{"):]).get("value") or "[]"
        rows = json.loads(val)
    finally:
        if created:
            _bsk("session", "stop", sid)

    out_rows = []
    import re as _re
    for cells in rows:
        if len(cells) < 4:
            continue
        course, name, span, status = cells[0], cells[1], cells[2], cells[3]
        m = _re.search(r"结束时间\s*(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})", span)
        due = f"{m.group(1)} {m.group(2)}" if m else ""
        st = "未交" if "未提交" in status or "未完成" in status else "已完成"
        extra = " ".join(x for x in (due, status, "") if x)[:120]
        out_rows.append((st, course, name, extra))
    out_rows.sort(key=lambda r: ({"未交": 0}.get(r[0], 1), r[3]))
    return out_rows


# ---------------------------------------------------------------- 输出
def emit(rows, as_json=False):
    if as_json:
        print(json.dumps([
            {"time": r[0].strftime("%Y-%m-%d %H:%M"), "source": r[1],
             "conv": r[2], "sender": r[3], "text": r[4]} for r in rows],
            ensure_ascii=False, indent=2))
        return
    for r in rows:
        print(f"{r[0].strftime('%Y-%m-%d %H:%M')} | {r[1]} | {r[2]} | {r[3]} | {r[4]}")


def pick_sources(arg):
    allsrc = ["wechat", "wecom", "chaoxing"]
    if not arg or arg == "all":
        return allsrc
    return [s.strip() for s in arg.split(",") if s.strip() in allsrc]


def gather(sources, cutoff, limit):
    rows = []
    for s in sources:
        try:
            if s == "wechat":
                part = wechat_rows(cutoff, limit)
            elif s == "wecom":
                part = wecom_rows(cutoff, limit)
            else:
                part = chaoxing_rows(cutoff, limit)
        except SystemExit as e:
            print(f"[跳过 {s}] {e}", file=sys.stderr)
            continue
        tag = {"wechat": "微信", "wecom": "企微", "chaoxing": "学习通"}[s]
        rows += [(w, tag, c, sd, t) for (w, c, sd, t) in part]
    rows.sort(key=lambda x: x[0])
    return rows


# ---------------------------------------------------------------- 命令
def _notices_bsk(limit=40, pages=3, keyword=""):
    """读学校门户通知公告（browser-skill 路线：复用浏览器里已登录的门户会话）。"""
    if not os.path.isfile(BSK):
        raise SystemExit(f"找不到 bsk.exe：{BSK}")
    st = _bsk_json("status", "--json")
    browsers = st.get("browsers") or []
    if not browsers:
        raise SystemExit("没有连上浏览器：先在浏览器里启用 browser-skill 扩展")
    bid = browsers[0]["instance_id"]
    sessions = _bsk_json("session", "list", "--json") or []
    created = False
    if sessions:
        sid = sessions[0]["session_id"]
    else:
        sstart = _bsk_json("session", "start", "--browser", bid, "--focus", "--json")
        sid = sstart.get("session_id")
        created = True
    try:
        _bsk("navigate", "--session", sid, MUC_URL)
        import time as _t
        _t.sleep(2.5)
        js = MUC_JS.replace("[API, PAGES, KEYWORD]", f"[{json.dumps(MUC_API)}, {pages}, {json.dumps(keyword or '')}]")
        rc, out, err = _bsk("evaluate", "--session", sid, "--json", js)
        if rc != 0:
            raise SystemExit(f"读取失败：{(err or out).strip()[:300]}")
        val = json.loads(out[out.index("{"):]).get("value") or "{}"
        data = json.loads(val)
        if data.get("error"):
            raise SystemExit(f"门户返回非 JSON（可能没登录）：{data.get('sample')}")
        return (data.get("rows") or [])[:limit]
    finally:
        if created:
            _bsk("session", "stop", sid)


def _notices_playwright(limit=40, pages=3):
    """Playwright 兜底：跑 tools/muc/portal_notices.py（需要它自己的登录态）。"""
    script = os.path.join(PROJ, "tools", "muc", "portal_notices.py")
    if not os.path.isfile(script):
        raise SystemExit(f"找不到 {script}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    pr = subprocess.run([XXT_PY or PY, script, "--limit", str(limit), "--pages", str(pages), "--json"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
    if pr.returncode != 0:
        raise SystemExit(f"门户读取失败：{(pr.stderr or pr.stdout).strip()[:300]}")
    try:
        return json.loads(pr.stdout[pr.stdout.index("["):])
    except Exception:
        raise SystemExit("门户输出不是 JSON")


def cmd_notices(a):
    since = parse_at(a.since) if a.since else None
    if not a.since and not a.all:
        since = parse_at(load_state().get("watermark_muc"))
    try:
        rows = _notices_bsk(limit=a.limit, pages=a.pages, keyword=getattr(a, "search", "") or "")
    except SystemExit as first:
        if os.environ.get("MSGPIPE_DEBUG"):
            print(f"[i] bsk 路线失败：{first}", file=sys.stderr)
        rows = _notices_playwright(limit=a.limit, pages=a.pages)
    if a.dept:
        rows = [r for r in rows if a.dept in (r.get("dept") or "")]
    if a.type:
        rows = [r for r in rows if a.type in (r.get("type") or "")]
    if since:
        keep = []
        for r in rows:
            t = parse_at(r.get("time") or "")
            if not t or t >= since:
                keep.append(r)
        rows = keep
    rows.sort(key=lambda r: r.get("time") or "", reverse=True)
    rows = rows[: a.limit]
    from datetime import datetime as _dt
    unified = []
    for r in rows:
        t = parse_at(r.get("time") or "") or _dt.min
        text = r.get("title", "") + (f"  {r['link']}" if r.get("link") else "")
        unified.append((t, "门户", r.get("dept") or "-", r.get("type", ""), text))
    emit(unified, a.json)
    if not a.json:
        print(f"[msgscan] {len(rows)} 条门户通知" + (f"，起点 {since}" if since else ""), file=sys.stderr)
    return 0


def cmd_doctor(a):
    """逐条线自检：依赖 / 登录态 / 水位。缺哪条就跳过哪条，不影响其它线。"""
    deep = getattr(a, "deep", False)
    ok = skip = bad = 0
    st = load_state()

    def line(name, status, need, fix):
        nonlocal ok, skip, bad
        icon = {"ok": "[OK]  ", "skip": "[--]  ", "bad": "[!!]  "}[status]
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            bad += 1
        print(f"{icon}{name:<22} {need}")
        if fix and status != "ok":
            print(f"        → {fix}")

    # 微信
    if not os.path.isdir(WECHAT_SCRIPTS):
        line("微信", "skip", "未安装（不需要微信可保持这样）", "scripts\\install-skills.cmd")
    elif not os.path.isfile(os.path.join(HOME, ".wechat-cli", "all_keys.json")):
        line("微信", "skip", "缺密钥（微信没登录过或没 init）", "cd ~/.wechat-cli && ./wxcli.cmd init")
    else:
        try:
            wechat_rows(None, 1)
            line("微信", "ok", "可读", "")
        except SystemExit as e:
            line("微信", "bad", str(e)[:90], "看 README 第 3 步")

    # 企微
    if not os.path.isfile(os.path.join(WECOM_SCRIPTS, "find_key.py")):
        line("企业微信", "skip", "未安装（不需要可保持这样）", "")
    elif not os.path.isfile(os.path.join(STATE_DIR, "wecom", "key.txt")):
        line("企业微信", "skip", "缺解密 key（还没抓过）", "python tools/wecom/find_key.py（一次 UAC）")
    else:
        try:
            wecom_rows(None, 1)
            line("企业微信", "ok", "可读", "")
        except SystemExit as e:
            line("企业微信", "bad", str(e)[:90], "重抓 key：tools/wecom/find_key.py")

    # 学习通消息
    if not os.path.isdir(os.path.join(CXMCP_DIR, "node_modules")):
        line("学习通消息", "skip", "未安装（不需要可保持这样）", "cd tools/cxmcp && npm install")
    elif not os.path.isfile(CXMCP_INDEX):
        line("学习通消息", "skip", "还没同步过", "scripts\\seed-cxmcp.cmd")
    else:
        try:
            chaoxing_rows(None, 1)
            line("学习通消息", "ok", "可读", "")
        except SystemExit as e:
            line("学习通消息", "bad", str(e)[:90], "scripts\\seed-cxmcp.cmd")

    # 学习通作业
    if not os.path.isfile(XXT_REPORT):
        line("学习通作业", "skip", "还没巡检过", "scripts\\msgscan.cmd assignments --refresh --source xxt")
    else:
        line("学习通作业", "ok", "有巡检报告", "")

    # 数你最灵
    if os.path.isfile(BSK) or (os.path.isdir(SX_PROFILE) and os.listdir(SX_PROFILE)):
        if deep:
            try:
                rows = smartestu_assignments()
                line("数你最灵", "ok", f"可读（{len(rows)} 条）", "")
            except SystemExit as e:
                line("数你最灵", "bad", str(e)[:90], "scripts\\smartestu.cmd --login")
        else:
            line("数你最灵", "ok", "有登录态（加 --deep 实测读取）", "")
    else:
        line("数你最灵", "skip", "未登录（不需要可保持这样）", "scripts\\smartestu.cmd --login")

    # 滴答 MCP
    prof = os.path.expanduser(os.path.join(HOME, ".dsh", "profiles", "web", "cordis.patch.yml"))
    if os.path.isfile(prof) and "mcp-dida365" in open(prof, encoding="utf-8", errors="replace").read():
        line("滴答 MCP", "ok", "profile 里已注册", "")
    else:
        line("滴答 MCP", "skip", "未注册（只出文本清单也能用）", "scripts\\install-mcp.cmd --apply")

    print(f"\n水位  微信={st.get('watermark_wechat') or '(未设)'}  "
          f"企微={st.get('watermark_wecom') or '(未设)'}  "
          f"学习通={st.get('watermark_chaoxing') or '(未设)'}  "
          f"门户={st.get('watermark_muc') or '(未设)'}")
    print("— 通知线 —")
    try:
        n = len(_notices_bsk(limit=1, pages=1))
        print(f"muc: OK（门户通知，bsk 读到 {n} 条）")
    except SystemExit as e:
        print(f"muc: 不可用 — {e}")
    for nm, hint in (("chapters", "msgscan chapters --course 工程图学"),
                     ("inbox", "msgscan inbox --limit 20")):
        path = os.path.join(PROJ, "tools", "xxt", {"chapters": "chapters_hw.py", "inbox": "inbox_notices.py"}[nm])
        flag = "OK" if (XXT_PY and os.path.isfile(path)) else "--"
        print(f"[{flag}]  {nm:<22}{hint}")
    print(f"小结  可用 {ok} 条 / 跳过 {skip} 条 / 待修 {bad} 条"
          f"（跳过 = 你没装，正常；待修 = 装了但坏了）")
    return 0 if bad == 0 else 1


def cmd_sources(a):
    """六条源一次点名：三条消息线（有水位）+ 三条作业/任务线。"""
    st = load_state()
    print(f"水位  微信={st.get('watermark_wechat') or '(未设)'}  "
          f"企微={st.get('watermark_wecom') or '(未设)'}  "
          f"学习通={st.get('watermark_chaoxing') or '(未设)'}  "
          f"门户={st.get('watermark_muc') or '(未设)'}")
    print("— 通知线 —")
    try:
        n = len(_notices_bsk(limit=1, pages=1))
        print(f"muc: OK（门户通知，bsk 读到 {n} 条）")
    except SystemExit as e:
        print(f"muc: 不可用 — {e}")
    print("— 消息线 —")
    for s in ("wechat", "wecom", "chaoxing"):
        try:
            if s == "wechat":
                wechat_rows(None, 1)
            elif s == "wecom":
                wecom_rows(None, 1)
            else:
                chaoxing_rows(None, 1)
            print(f"{s}: OK（最近 1 条读数正常）")
        except SystemExit as e:
            print(f"{s}: 不可用 — {e}")
    print("— 作业线 —")
    print(f"xxt: {'OK（报告在 ' + XXT_REPORT + '）' if os.path.isfile(XXT_REPORT) else '不可用 — 没有巡检报告，先跑 assignments --refresh'}")
    # 数你最灵：只看登录态，不联网
    if os.path.isfile(BSK):
        print("smartestu: OK（走 bsk，用 Edge 里已登录的会话）")
    elif os.path.isdir(SX_PROFILE):
        print("smartestu: 已装 Playwright profile，未实测（assignments --source smartestu 可验）")
    else:
        print("smartestu: 不可用 — 跑 scripts\\smartestu.cmd --login 登录一次")
    print("— 任务线 —")
    prof = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"),
                        ".dsh", "profiles", "web", "cordis.patch.yml")
    if os.path.isfile(prof) and "mcp-dida365" in io.open(prof, encoding="utf-8", errors="ignore").read():
        print("dida: OK（profile 里已注册 mcp-dida365）")
    else:
        print("dida: 未接入 — 不想自动建任务可以不管")


def cmd_sessions(a):
    cutoff = parse_at(a.since)
    rows = gather(pick_sources(a.source), cutoff, None)
    agg = {}
    for w, src, conv, sd, t in rows:
        k = (src, conv)
        c, last = agg.get(k, (0, w))
        agg[k] = (c + 1, max(last, w))
    out = sorted(agg.items(), key=lambda kv: kv[1][1], reverse=True)
    if a.json:
        print(json.dumps([{"source": k[0], "conv": k[1], "count": v[0],
                           "last": v[1].strftime("%Y-%m-%d %H:%M")}
                          for k, v in out], ensure_ascii=False, indent=2))
        return
    for (src, conv), (c, last) in out:
        print(f"{last.strftime('%Y-%m-%d %H:%M')} | {src} | {conv} | {c} 条")


WM_KEY = {"wechat": "watermark_wechat", "wecom": "watermark_wecom", "chaoxing": "watermark_chaoxing", "muc": "watermark_muc"}


def cmd_since(a):
    st = load_state()
    srcs = pick_sources(a.source)
    cutoff = parse_at(a.at)
    if cutoff is None:
        stamps = [parse_at(st.get(WM_KEY[k])) for k in srcs]
        stamps = [s for s in stamps if s]
        cutoff = min(stamps) if stamps else None
    rows = gather(srcs, cutoff, a.limit)
    if not a.raw:
        rows = clean_rows(rows, a.width)
    emit(rows, a.json)
    if not a.json:
        print(f"[msgscan] {len(rows)} 条，起点 {cutoff or '全部'}", file=sys.stderr)
        if not rows:
            print("[msgscan] 一条也没读到——如果某条线没装，属正常；跑 "
                  "`msgscan.cmd doctor` 看现在能用哪几条", file=sys.stderr)


def cmd_search(a):
    cutoff = parse_at(a.since)
    rows = [r for r in gather(pick_sources(a.source), cutoff, None)
            if a.keyword in r[4] or a.keyword in r[2]]
    if not a.raw:
        rows = clean_rows(rows, a.width)
    if a.limit:
        rows = rows[-a.limit:]
    emit(rows, a.json)
    if not a.json:
        print(f"[msgscan] 命中 {len(rows)} 条", file=sys.stderr)


def cmd_assignments(a):
    src = (a.source or "all").lower()
    rows = []
    if src in ("all", "xxt"):
        try:
            rows += xxt_assignments(a.refresh)
        except SystemExit as e:
            print(f"[跳过 学习通] {e}", file=sys.stderr)
    if src in ("all", "smartestu"):
        try:
            rows += smartestu_assignments()
        except SystemExit as e:
            print(f"[跳过 数你最灵] {e}", file=sys.stderr)
    if not rows:
        print("（两条作业线都没读到：学习通需要先 --refresh 巡检，数你最灵需要先 --login）\n"
              "  跑 `msgscan.cmd doctor` 看具体缺什么", file=sys.stderr)
        return

    if a.json:
        print(json.dumps([{"status": r[0], "course": r[1], "title": r[2], "extra": r[3],
                           "due": _assign_due(r).strftime("%Y-%m-%d %H:%M") if _assign_due(r) else ""}
                          for r in rows], ensure_ascii=False, indent=2))
        return

    new_todo, changed, gone = _assign_diff(rows)
    todo = [r for r in rows if (r[0] or "") in ("未交", "未提交", "未完成")]
    pend = [r for r in rows if (r[0] or "") == "待批阅"]

    if new_todo:
        print("## 新的未交（上次没有 / 状态变了）")
        for title, due, prev, s_ in new_todo:
            print(f"  + {title}" + (f" · 截止 {due}" if due else "")
                  + (f" · 之前 {prev}" if prev else "") + f" · {s_}")
    if changed:
        print("## 状态变化")
        for title, old, new in changed:
            print(f"  ~ {title}：{old} → {new}")
    if gone:
        print(f"## 快照里消失：{len(gone)} 条")

    print("## 仍需处理（未交 + 待批阅）")
    for st, course, title, extra in todo + pend:
        due = _assign_due((st, course, title, extra))
        print(f"  {st} | {course} | {title} | {due.strftime('%Y-%m-%d %H:%M') if due else extra}")
    print(f"—— 共 {len(rows)} 条：未交 {len(todo)}、待批阅 {len(pend)}、其余 {len(rows)-len(todo)-len(pend)} 已交"
          + ("；本次无新增" if not (new_todo or changed) else ""))


# ---------- 作业状态快照：只比对变化，不建任务 ----------
ASSIGN_STATE = os.path.join(STATE_DIR, "assignments.json")


def _assign_key(src, course, title):
    return f"{src}|{course}|{title}"


def _assign_src(row):
    extra = row[3] or ""
    if "未提交" in extra or ("已完成" in extra and "剩余" not in extra):
        return "数你最灵"
    return "学习通"


def _assign_due(row, now=None):
    """从 extra 抠截止：数你最灵是 'YYYY-MM-DD HH:MM …'，学习通是 '剩余N小时M分钟'。"""
    import re as _re
    from datetime import datetime as _dt, timedelta as _td
    st, course, title, extra = row
    now = now or _dt.now()
    m = _re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", extra or "")
    if m:
        return _dt.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M")
    m = _re.search(r"剩余(\d+)小时(\d+)分钟", extra or "")
    if m:
        return now + _td(hours=int(m.group(1)), minutes=int(m.group(2)))
    return None


def _assign_diff(rows):
    """与上次快照比，返回 (新增未交, 状态变化, 消失)。只读，不动滴答。"""
    from datetime import datetime as _dt
    now = _dt.now()
    st_map = json.load(io.open(ASSIGN_STATE, encoding="utf-8")) if os.path.isfile(ASSIGN_STATE) else {}
    new_todo, changed, seen = [], [], set()
    for row in rows:
        src = _assign_src(row)
        key = _assign_key(src, row[1], row[2])
        seen.add(key)
        status = row[0] or ""
        due = _assign_due(row, now)
        rec = st_map.get(key, {})
        prev = rec.get("status")
        todo = status in ("未交", "未提交", "未完成")
        if todo and prev != status:
            new_todo.append((row[2], due.strftime("%Y-%m-%d %H:%M") if due else "", prev, src))
        elif prev and prev != status:
            changed.append((row[2], prev, status))
        rec.update({"status": status, "due": due.strftime("%Y-%m-%d %H:%M") if due else "",
                    "extra": row[3], "seen": now.strftime("%Y-%m-%dT%H:%M:%S")})
        st_map[key] = rec
    gone = [k for k in st_map if k not in seen and st_map[k].get("status") in ("未交", "未提交", "未完成")]
    for k in gone:
        st_map[k]["status"] = "已消失"
    json.dump(st_map, io.open(ASSIGN_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return new_todo, changed, gone


def _xxt_script(name):
    return os.path.join(PROJ, "tools", "xxt", name)


def _run_xxt_script(name, args, json_out):
    """用学习通 venv 的 python 跑 tools/xxt 下的 Playwright 脚本。"""
    if not XXT_PY:
        raise SystemExit("没找到学习通 venv：先按 README 第 5 步建 tools/xxt/chaoxing-agent-cli-main/.venv")
    script = _xxt_script(name)
    if not os.path.isfile(script):
        raise SystemExit(f"缺脚本：{script}")
    env = dict(os.environ)
    env.update({"TEMP": os.path.join(STATE_DIR, "xxt", "tmp"),
                "TMP": os.path.join(STATE_DIR, "xxt", "tmp"),
                "PLAYWRIGHT_BROWSERS_PATH": os.path.join(PROJ, "tools", "xxt", "browsers"),
                "XXT_STATE_DIR": os.path.join(STATE_DIR, "xxt"),
                "PYTHONIOENCODING": "utf-8"})
    cmd = [XXT_PY, script] + args + (["--json"] if json_out else [])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, stdin=subprocess.DEVNULL, timeout=600)
    if r.returncode != 0:
        raise SystemExit((r.stderr or r.stdout or "").strip().splitlines()[-1:] or "脚本失败")
    return r.stdout, r.stderr


def cmd_chapters(a):
    args = ["--course", a.course]
    if a.all:
        args.append("--all")
    out, err = _run_xxt_script("chapters_hw.py", args, a.json)
    if a.json:
        print(out.strip())
    else:
        print(out.rstrip())
        if err.strip():
            print(err.rstrip(), file=sys.stderr)


def cmd_inbox(a):
    out, err = _run_xxt_script("inbox_notices.py", ["--limit", str(a.limit)], a.json)
    if a.json:
        print(out.strip())
    else:
        print(out.rstrip())
        if err.strip():
            print(err.strip(), file=sys.stderr)


def cmd_advance(a):
    at = parse_at(a.at)
    if not at:
        raise SystemExit("advance 需要 --at")
    st = load_state()
    keys = [WM_KEY[k] for k in pick_sources(a.source)]
    for k in keys:
        st[k] = at.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    save_state(st)
    print(f"[msgscan] 水位已推进到 {at}")


def main():
    ap = argparse.ArgumentParser(prog="msgscan", description="微信/企微/学习通统一门面")
    ap.add_argument("--json", action="store_true", dest="json_main", help="JSON 输出")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("sources",):
        p = sub.add_parser(name, help="三线自检")
        p.set_defaults(func=cmd_sources)

    p = sub.add_parser("sessions", help="会话列表（条数 + 最后时间）")
    p.add_argument("--since")
    p.add_argument("--source", default="all")
    p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("since", help="断点之后的消息")
    p.add_argument("--at")
    p.add_argument("--source", default="all")
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--raw", action="store_true", help="不过滤系统消息、不截断")
    p.add_argument("--width", type=int, default=300, help="正文截断宽度，默认 300")
    p.set_defaults(func=cmd_since)

    p = sub.add_parser("search", help="关键词检索")
    p.add_argument("keyword")
    p.add_argument("--since")
    p.add_argument("--source", default="all")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--raw", action="store_true")
    p.add_argument("--width", type=int, default=300)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("assignments", help="学习通作业状态")
    p.add_argument("--refresh", action="store_true", help="学习通重新巡检")
    p.add_argument("--source", default="all",
                   help="all | xxt | smartestu（默认 both；数你最灵会开一个可见的 Agent 窗口，约 10 秒）")
    p.set_defaults(func=cmd_assignments)

    p = sub.add_parser("doctor", help="逐条线自检（缺哪条就跳过哪条）")
    p.add_argument("--deep", action="store_true", help="真的去读一次（数你最灵会开窗口）")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("chapters", help="学习通课程「章节」里的作业任务点")
    p.add_argument("--course", default="工程图学", help="课程名关键词")
    p.add_argument("--all", action="store_true", help="读全部章节（默认只读标题含「作业」的）")
    p.set_defaults(func=cmd_chapters)

    p = sub.add_parser("inbox", help="学习通站内信 Inbox（作业提醒等）")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser("notices", help="学校门户通知公告（校级/部门级，只读）")
    p.add_argument("--since", help="只看这个时间之后（默认用 watermark_muc）")
    p.add_argument("--all", action="store_true", help="忽略水位，看最近几页")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--pages", type=int, default=3, help="翻几页（每页 10 条）")
    p.add_argument("--search", help="站内搜索关键词（走门户的 searchValue）")
    p.add_argument("--dept", help="按部门关键词过滤")
    p.add_argument("--type", help="按类型过滤，如 教学通知/公示公告")
    p.add_argument("--width", type=int, default=300)
    p.set_defaults(func=cmd_notices)

    p = sub.add_parser("advance", help="推进水位")
    p.add_argument("--at", required=True)
    p.add_argument("--source", default="all")
    p.set_defaults(func=cmd_advance)

    for _p in sub.choices.values():
        _p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = ap.parse_args()
    a.json = bool(getattr(a, "json", False) or a.json_main)
    a.func(a)


if __name__ == "__main__":
    main()
