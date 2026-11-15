# -*- coding: utf-8 -*-
"""给学习通消息线（tools/cxmcp）准备登录态。

cxmcp 用自己的持久化浏览器 profile，不等同于 xxt 的 storage_state。
两个模式：
  python seed_cxmcp_cookies.py --check   只检查现在是否已登录（不开窗口）
  python seed_cxmcp_cookies.py           开一个可见的 Edge，登录一次，然后把
                                         会话级 cookie 的 expires 改一年（否则关掉就丢）

依赖：tools/xxt/.venv 里的 playwright（pip install playwright && playwright install chromium）
"""
import os, sys, time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(PROJ, "tools", "cxmcp", "user-profile")
ONCE = int(time.time()) + 365 * 86400


def probe(ctx):
    try:
        r = ctx.request.get("https://i.chaoxing.com/base/getNoticeCount",
                            headers={"Accept": "application/json, text/plain, */*"})
        return r.ok and '"msg":true' in r.text()
    except Exception:
        return False


def main():
    from playwright.sync_api import sync_playwright
    check = "--check" in sys.argv
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="msedge", headless=check)
        try:
            ok = probe(ctx)
            if ok:
                print("[=] 已登录，profile 可用：", PROFILE)
                if not check:
                    n = 0
                    for c in ctx.cookies():
                        if c.get("expires", -1) < 0:
                            c["expires"] = ONCE; n += 1
                    if n:
                        ctx.add_cookies([{k: c[k] for k in ("name", "value", "domain", "path")}
                                         | {"expires": ONCE, "httpOnly": c.get("httpOnly", False),
                                            "secure": c.get("secure", False), "sameSite": c.get("sameSite", "Lax")}
                                         for c in ctx.cookies() if c.get("expires", -1) < 0])
                        print(f"[ok] 已把 {n} 个会话 cookie 的过期时间改成一年")
                return 0
            if check:
                print("[x] 未登录。跑不带 --check 的版本，在弹出的 Edge 里登录一次")
                return 3
            print("[>] 在弹出的 Edge 里登录学习通（i.chaoxing.com），最长等 5 分钟…")
            ctx.pages[0].goto("https://i.chaoxing.com/base", wait_until="domcontentloaded")
            for _ in range(60):
                time.sleep(5)
                if probe(ctx):
                    break
            else:
                print("[x] 超时没检测到登录")
                return 3
            n = 0
            for c in ctx.cookies():
                if c.get("expires", -1) < 0:
                    n += 1
            if n:
                ctx.add_cookies([{k: c[k] for k in ("name", "value", "domain", "path")}
                                 | {"expires": ONCE, "httpOnly": c.get("httpOnly", False),
                                    "secure": c.get("secure", False), "sameSite": c.get("sameSite", "Lax")}
                                 for c in ctx.cookies() if c.get("expires", -1) < 0])
            print(f"[ok] 登录成功，已把 {n} 个会话 cookie 改成一年有效期；profile：{PROFILE}")
            return 0
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
