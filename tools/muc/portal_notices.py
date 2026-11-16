#!/usr/bin/env python3
"""读 MUC 信息门户的通知公告（校级/部门级），只读、不点任何东西。

数据来源：https://my.muc.edu.cn/comsys-portal-notice-web/getNoticeByPage
需要门户登录态，存在 state/muc/profile（Playwright 持久化 profile）。
第一次用要跑一次 `--login`，在弹出的窗口里扫码/输密码登录，之后长期有效。

用法：
  python portal_notices.py --check
  python portal_notices.py --login
  python portal_notices.py --since "2026-11-16 00:00" --limit 30
  python portal_notices.py --dept 教务 --json
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]


def _env():
    """Playwright 和 Chrome 都会往系统临时目录写，沙箱下会 EPERM，必须先钉死。"""
    tmp = PROJ / "state" / "xxt" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(tmp)
    os.environ["TMP"] = str(tmp)
    browsers = PROJ / "tools" / "xxt" / "browsers"
    if browsers.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))


_env()

PROFILE = PROJ / "state" / "muc" / "profile"
HOME_URL = "http://my.muc.edu.cn/page/11#/"
API = "/comsys-portal-notice-web/getNoticeByPage"

FETCH_JS = """
async ([api, pageNum, pageSize]) => {
  const r = await fetch(api, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pageNum, pageSize}),
    credentials: 'include'
  });
  const text = await r.text();
  try {
    const j = JSON.parse(text);
    const tables = (j.datas && j.datas.tables) || [];
    return {ok: true, rows: tables.map(x => ({
      time: x.notice_release_time || x.notice_first_time || '',
      type: x.notice_type_name || '',
      dept: x.organization_name || '',
      title: x.notice_title || '',
      link: x.notice_link || '',
      id: x.notice_id || '',
      content: (x.notice_content || '').replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim().slice(0, 400)
    }))};
  } catch (e) {
    return {ok: false, error: 'not-json', sample: text.slice(0, 200), len: text.length};
  }
}
"""

CHECK_JS = """
() => {
  const t = document.body.innerText || '';
  return {
    url: location.href,
    logged_in: /同学\\s*(上午|下午|晚上)好/.test(t) || /退出/.test(t),
    has_portal: /信息门户|通知公告/.test(t)
  };
}
"""


def _browsers():
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _read_cookies_safe():
    """在浏览器启动前读 cookie：Chromium 打开时文件被锁，先拷一份再读。"""
    cookies = []
    try:
        import shutil, tempfile
        sys.path.insert(0, str(HERE))
        from edge_cookies import read_cookies
        src = PROFILE / "Default" / "Network"
        if not (src / "Cookies").exists():
            return cookies
        tmp = Path(tempfile.mkdtemp(prefix="muc-cookies-"))
        for name in ("Cookies", "Cookies-journal"):
            if (src / name).exists():
                shutil.copy2(src / name, tmp / name)
        (tmp / "Local State").write_bytes((PROFILE / "Local State").read_bytes())
        (tmp / "Default" / "Network").mkdir(parents=True, exist_ok=True)
        for name in ("Cookies", "Cookies-journal"):
            if (tmp / name).exists():
                shutil.move(str(tmp / name), str(tmp / "Default" / "Network" / name))
        cookies = read_cookies(tmp, ["my.muc.edu.cn", "ca.muc.edu.cn"])
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as exc:
        print(f"[i] cookie 复用失败：{exc}", file=sys.stderr)
    return cookies


def _open(headless: bool):
    cookies = _read_cookies_safe()
    pw = _browsers()().start()
    PROFILE.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE),
        channel="msedge",
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception as exc:
            print(f"[i] cookie 注入失败：{exc}", file=sys.stderr)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, ctx, page


def _goto(page, url, wait=1500):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(wait)


def cmd_check():
    pw, ctx, page = _open(headless=True)
    try:
        _goto(page, HOME_URL, 2500)
        state = page.evaluate(CHECK_JS)
        got = page.evaluate(FETCH_JS, [API, 1, 5])
        out = {
            "profile": str(PROFILE),
            "url": state.get("url"),
            "logged_in": bool(state.get("logged_in")),
            "api_ok": bool(got.get("ok")),
            "rows": len(got.get("rows") or []),
        }
        if not out["logged_in"] or not out["api_ok"]:
            out["hint"] = "没登录或接口不通，跑：msgscan notices --login（在弹出的窗口里登录一次）"
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out["api_ok"] else 3
    finally:
        ctx.close()
        pw.stop()


def cmd_login(wait_s=300):
    pw, ctx, page = _open(headless=False)
    try:
        _goto(page, HOME_URL, 2000)
        print("[i] 请在打开的窗口里登录中央民族大学信息门户（统一身份认证）", flush=True)
        ok = False
        for _ in range(int(wait_s / 3)):
            page.wait_for_timeout(3000)
            try:
                got = page.evaluate(FETCH_JS, [API, 1, 5])
            except Exception:
                continue
            if got.get("ok") and got.get("rows"):
                ok = True
                break
        print(json.dumps({"authenticated": ok, "profile": str(PROFILE)}, ensure_ascii=False))
        return 0 if ok else 4
    finally:
        ctx.close()
        pw.stop()


def _parse_time(s: str):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip()[:19], fmt)
        except ValueError:
            continue
    return None


def fetch_rows(since=None, limit=40, dept=None, ntype=None, pages=4):
    pw, ctx, page = _open(headless=True)
    try:
        _goto(page, HOME_URL, 2500)
        state = page.evaluate(CHECK_JS)
        if not state.get("logged_in"):
            raise SystemExit("门户没登录：跑 msgscan notices --login 登录一次")
        rows, seen = [], set()
        for page_num in range(1, pages + 1):
            got = page.evaluate(FETCH_JS, [API, page_num, 10])
            if not got.get("ok"):
                raise SystemExit(f"接口返回非 JSON：{got.get('sample')}")
            batch = got.get("rows") or []
            if not batch:
                break
            stop = False
            for r in batch:
                key = r.get("id") or r.get("title")
                if key in seen:
                    continue
                seen.add(key)
                t = _parse_time(r.get("time") or "")
                if since and t and t < since:
                    stop = True
                    continue
                if dept and dept not in (r.get("dept") or ""):
                    continue
                if ntype and ntype not in (r.get("type") or ""):
                    continue
                r["_t"] = t
                rows.append(r)
            if stop or len(rows) >= limit:
                break
            page.wait_for_timeout(300)
        rows.sort(key=lambda r: r["_t"] or datetime.min, reverse=True)
        return rows[:limit]
    finally:
        ctx.close()
        pw.stop()


def cmd_list(a):
    since = None
    if a.since:
        since = _parse_time(a.since)
        if not since:
            raise SystemExit(f"时间格式看不懂：{a.since}")
    rows = fetch_rows(since=since, limit=a.limit, dept=a.dept, ntype=a.type, pages=a.pages)
    if a.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "_t"} for r in rows], ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(f"{r['time']} | {r['type']} | {r['dept']} | {r['title']}")
        print(f"共 {len(rows)} 条")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="读 MUC 信息门户通知公告（只读）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--wait", type=int, default=300, help="登录等待秒数")
    ap.add_argument("--since", help='只看这个时间之后的，如 "2026-11-16 00:00"')
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--pages", type=int, default=4, help="最多翻几页（每页 10 条）")
    ap.add_argument("--dept", help="按部门关键词过滤")
    ap.add_argument("--type", help="按类型过滤，如 教学通知/公示公告")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        return cmd_check()
    if a.login:
        return cmd_login(a.wait)
    return cmd_list(a)


if __name__ == "__main__":
    sys.exit(main())
