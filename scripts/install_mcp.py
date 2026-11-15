# -*- coding: utf-8 -*-
"""把滴答 MCP 写进 DSH profile（幂等）。

用法：install_mcp.py [--apply]
  不带 --apply 只打印将要写入的块与目标文件，不动任何东西。
从哪里取令牌：state/dsh/dida-token.txt（一行，dp_ 开头）；没有就问人。
"""
import io, os, re, sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(PROJ, "state", "dsh", "dida-token.txt")
PROFILE = os.path.expanduser(r"~\\.dsh\\profiles\\web\\cordis.patch.yml")

BLOCK = """- insert:
    - id: mcp-dida365
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: dida365
        transport: streamable-http
        url: https://mcp.dida365.com
        headers:
          Authorization: 'Bearer {token}'
"""


def token():
    if os.path.exists(TOKEN_FILE):
        t = io.open(TOKEN_FILE, encoding="utf-8").read().strip()
        if re.fullmatch(r"dp_[A-Za-z0-9]+", t):
            return t
    return None


def main():
    apply_ = "--apply" in sys.argv
    t = token()
    if not t:
        print("[x] 没有令牌：把 dp_ 开头的个人访问令牌写进", TOKEN_FILE)
        print("    令牌在 https://developer.dida365.com 的应用页面里生成")
        return 2
    if not os.path.exists(PROFILE):
        print("[x] 找不到 profile：", PROFILE)
        print("    DSH 至少启动过一次才会有；先确认 DSH 装好")
        return 2
    body = io.open(PROFILE, encoding="utf-8").read()
    if "mcp-dida365" in body:
        print("[=] profile 里已经有 mcp-dida365，跳过（要换令牌就手动改 Authorization 那行）")
        return 0
    block = BLOCK.format(token=t)
    print("目标：", PROFILE)
    print("将追加：\n" + block)
    if not apply_:
        print("[dry-run] 加 --apply 才会真的写")
        return 0
    bak = PROFILE + ".bak-" + __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    io.open(bak, "w", encoding="utf-8").write(body)
    if not body.endswith("\n"):
        body += "\n"
    io.open(PROFILE, "w", encoding="utf-8").write(body + block)
    print("[ok] 已写入；备份在", bak)
    print("     保存即热加载，新开对话后应出现 58 个 mcp__dida365__* 工具")
    return 0


if __name__ == "__main__":
    sys.exit(main())
