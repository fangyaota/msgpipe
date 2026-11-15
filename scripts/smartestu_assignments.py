# -*- coding: utf-8 -*-
"""读数你最灵（smartestu.cn）的作业表，不依赖 browser-skill。

用自己的持久化浏览器 profile（state/smartestu/profile），登录一次即可长期复用。
  --check    只探测是否已登录（无头，不开窗口）
  --login    开可见窗口登录一次
  默认       有登录态就无头读表，输出 JSON：[["课程","作业名","时段","状态"], ...]
"""
import json, os, sys, time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(PROJ, "state", "smartestu", "profile")
URL = "https://smartestu.cn/assignment"
ROWS_JS = """Array.from(document.querySelectorAll('table tbody tr'))
  .map(tr=>Array.from(tr.cells).map(td=>td.innerText.trim().replace(/\\s+/g,' ')))"""
COUNT_JS = "document.querySelectorAll('table tbody tr').length"
LOGGED_IN_JS = """(() => {
  const hasForm = !!document.querySelector('input[type=password]');
  const rows = document.querySelectorAll('table tbody tr').length;
  return JSON.stringify({form: hasForm, rows});
})()"""


def read_rows(page, wait_s=30):
    for _ in range(int(wait_s / 1.5)):
        try:
            st = json.loads(page.evaluate(LOGGED_IN_JS))
        except Exception:
            st = {"form": False, "rows": 0}
        if st.get("form"):
            return None, 0
        if st.get("rows"):
            return page.evaluate(ROWS_JS), st["rows"]
        time.sleep(1.5)
    return [], 0


def main():
    from playwright.sync_api import sync_playwright
    mode = "check" if "--check" in sys.argv else ("login" if "--login" in sys.argv else "read")
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    headless = mode != "login"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="msedge",
                                                   headless=headless,
                                                   viewport={"width": 1440, "height": 900})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded")
            rows, n = read_rows(page, wait_s=20)
            if rows is None:
                if mode == "check":
                    print("[x] 未登录（页面出现密码框）。跑 --login 登录一次")
                    return 3
                if mode == "read":
                    print("[x] 登录态失效，先跑 scripts\\smartestu.cmd --login", file=sys.stderr)
                    return 3
                print("[>] 在弹出的窗口里登录 smartestu.cn（学校 + 学号 + 密码），最长等 5 分钟…")
                for _ in range(60):
                    time.sleep(5)
                    rows, n = read_rows(page, wait_s=2)
                    if rows:
                        break
                if not rows:
                    print("[x] 超时没等到作业表")
                    return 3
            if mode == "check":
                print(f"[=] 已登录，读到 {n} 行作业")
                return 0
            if mode == "login":
                print(f"[ok] 登录成功，读到 {n} 行；profile：{PROFILE}")
                return 0
            print(json.dumps(rows, ensure_ascii=False))
            return 0
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
