---
name: wecom-local
description: 查询、导出本机企业微信（WXWork）聊天记录——按会话/时间/关键词检索，增量拉断点之后的新消息，导出文件与图片。当用户提到企业微信、企微、WXWork、看点企微群消息、企微课程群通知、把企微也纳入待办时使用；与微信（wechat-local）是两套独立数据，互不影响。
---

# 本机企业微信数据分析（wecom-local）

企业微信 PC 端的 `message.db` 也是 wxSQLite3 加密库，本 skill 用内存里抓到的 16 字节 key 离线解密，**不需要关企业微信，也不需要管理员签名的机器人**。

## 一条命令能用

```bash
SK="D:/Workspace/msgpipe/tools/wecom/wecom.py"
PY="D:/Python/Python315/python.exe"

"$PY" "$SK" info              # 环境、key、已解密库、消息数与时间范围
"$PY" "$SK" sessions          # 会话列表（按最后消息倒序，带条数）
"$PY" "$SK" messages --limit 20
"$PY" "$SK" messages --since "2026-11-14 00:00" --conv 英语
"$PY" "$SK" search 申诉 --since "2026-11-01"
"$PY" "$SK" watch             # 只看断点之后的新消息，并自动推进断点
"$PY" "$SK" media 10 --out D:/Workspace/_tmp/files   # 按 message_id 导出原件
```

输出是制表符分隔的一行一条：`时间 \t 会话 \t 发送者 \t 类型 \t 正文`（正文里的换行显示为 ` ⏎ `）。加 `--json` 拿结构化数据。

时间参数接受 `2026-11-14 22:03`、`2026-11-14T22:03:00+08:00`、`11-14`（当年）。

## 环境事实

| 东西 | 位置 |
|---|---|
| 入口脚本 | `D:\Workspace\msgpipe\tools\wecom\wecom.py` |
| key | `D:\Workspace\msgpipe\state\wecom/key.txt`（32 位十六进制，明文，别外传） |
| 解密缓存 | `D:\Workspace\msgpipe\state\wecom/cache\<账号>\*.db` |
| 断点与库指纹 | `D:\Workspace\msgpipe\state\wecom/state.json`（`watermark_wecom`） |
| 企业微信数据根 | `C:\Users\Apple\Documents\WXWork\<账号>\Data\*.db`（主账号 `<账号>`） |
| 抓 key 脚本 | `scripts/find_key.py`（需 UAC，4 秒出结果） |
| Python | `D:/Python/Python315/python.exe`（pycryptodome + numpy 已装） |

## 维护：key 失效怎么办

企业微信升级或换账号后 key 会变，表现是 `refresh` 报 `key 对 message.db 失效`。跑：

```bash
"$PY" "$SK" scan-key     # 弹一次 UAC，扫 WXWork.exe 内存，抓到 key 后自动重解密
```

手工兜底：`"$PY" "$SK" set-key <32位hex>`。

## 局限（必须知道）

- **本地库只有近期少量会话**：实测 51 条 / 7 个会话（2026-11-01 → 2026-11-15），历史在服务端。所以它适合「断点之后有什么新消息」，不适合「翻三个月前」。
- 卡片类消息（type 561/145 等）只能拿到标题文字，**拿不到里面的链接**；链接类（35）和文档链接（13）能拿到 URL。
- 图片/文件按 `Cache\{File,Image}\` 里的同名文件导出；发出去的消息原件不一定还在本地。
- 解密产物是本机敏感数据，放 `D:\Workspace\msgpipe\state\wecom/`，别进网盘、别进 git。

## 与 wechat-todo 的关系

`wechat-todo` 每次跑「更新待办」时，会额外跑一次 `watch` 拿企微增量，用**独立断点** `watermark_wecom`，和微信那条断点互不影响。企微消息与微信消息合并去重后一起进滴答。
