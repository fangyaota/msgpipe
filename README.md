# msgpipe

微信、企业微信、学习通三条线 → 待办与滴答清单，全部代码、数据和状态都在这一个文件夹里。

## 目录

```
D:\Workspace\msgpipe\
  README.md            本文件：项目地图与命令
  docs\
    使用说明.md        日常怎么用（触发语、结果在哪看、排障）
    消息来源.md        四条数据线各自的口径、边界、已知坑
  待办\                产出（人看的）
    今日待办.md
    待办总表.md
    日期纪要\YYYY-MM-DD.md
    原始消息\YYYY-MM-DD\    每轮扫到的原始文本
    文件\YYYY-MM\           归档的附件（通知/名单/课程作业/竞赛）
  skills\               三个 DSH 技能的源文件（改这里，再跑 install-skills.cmd 同步）
    wechat-todo\        流程规则书 + scripts\msgscan.cmd 转发器
    wechat-local\       微信检索（search_all.py、zstd 依赖等）
    wecom-local\        企业微信检索（wecom.py）
  scripts\
    msgscan.py         四线统一门面（唯一入口）
    msgscan.cmd        Windows 包装器，固定编码与解释器
    install-skills.cmd 把 skills\ 同步到 %USERPROFILE%\.dsh\skills
    restore-wechat-cli.cmd  从 state\wechat 还原 ~/.wechat-cli 配置与密钥
    install-mcp.cmd    把滴答 MCP 写进 DSH profile（幂等，已存在就跳过）
  tools\
    xxt\               学习通：chaoxing-agent-cli 源码 + .venv + Chromium + xxt.cmd + scan_all.py
      browsers\        Playwright Chromium（PLAYWRIGHT_BROWSERS_PATH）
      tmp\             Playwright 临时目录（TEMP/TMP）
    cxmcp\             学习通 IM：ChaoXingMessageMCP + Edge profile + messages\ + dump.mjs
    wecom\             企业微信：wecom.py（解密+查询）、find_key.py、wxwork_crypto.py 等
  state\
    msgscan.json       四线水位 watermark_wechat / watermark_wecom / watermark_chaoxing
    wechat\            ~/.wechat-cli 的配置与密钥快照（all_keys.json、config.json、tool\；不含 deps）
    wecom\             企微 key.txt、解密缓存 cache\、状态 state.json
    xxt\               学习通登录态 session.enc / session.key
```

## 常用命令

```bash
cd /d/Workspace/msgpipe
./scripts/msgscan.cmd sources                  # 四线自检
./scripts/msgscan.cmd since                    # 断点之后的新消息（时间 | 来源 | 会话 | 发送者 | 正文）
./scripts/msgscan.cmd since --at "2026-11-15 16:00" --limit 20
./scripts/msgscan.cmd sessions --since         # 只列有更新的会话
./scripts/msgscan.cmd search 体测              # 跨四线关键词
./scripts/msgscan.cmd assignments              # 学习通作业 + 数你最灵作业（默认两条都查）
./scripts/msgscan.cmd assignments --refresh    # 先巡检 14 门课再列（1-2 分钟）
./scripts/msgscan.cmd advance --at "2026-11-15 16:10"   # 推进水位
```

## 四条线

| 线 | 干什么 | 数据从哪来 |
| --- | --- | --- |
| 微信 | 群通知、作业、截止日期 | `~/.wechat-cli`（第三方 wxcli）+ `~/.dsh/skills/wechat-local` 的 search_all.py |
| 企业微信 | 课程群、内部部署 | `tools/wecom` 解密 `C:\Users\<你>\Documents\WXWork\<账号>\Data` |
| 学习通 · 作业 | 作业状态与截止 | `tools/xxt`（xxt.exe 走网页版）+ `tools/xxt/courses_report.json` |
| 学习通 · 消息 | 课程群聊 | `tools/cxmcp`（fe.chaoxing.com/webim 的 store）→ `messages\` |

数你最灵（`smartestu.cn`）不是独立数据源，是 `assignments` 里额外开一个可见浏览器窗口读的作业表。

## 打包了什么、没打包什么

**已打包进本项目**

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 三个 DSH 技能 | `skills\{wechat-todo,wechat-local,wecom-local}` | 规则书 + 全部脚本，`install-skills.cmd` 一键装 |
| 微信配置与密钥 | `state\wechat\{all_keys.json,config.json,tool,wxcli.cmd}` | 520 KB；`restore-wechat-cli.cmd` 还原 |
| 滴答 MCP 配置 | `state\dsh\cordis.patch.yml` + `dida-token.txt` | profile 完整快照（令牌已脱敏）＋真实令牌；`install-mcp.cmd` 一键写入 |
| 企微 key + 解密缓存 | `state\wecom\` | key.txt、cache\、state.json |
| 学习通登录态 | `state\xxt\session.enc,session.key` | 加密存储，换机器可直接用 |
| 四线水位 | `state\msgscan.json` | 断点，决定下一轮从哪扫 |
| 作业巡检结果 | `tools\xxt\courses_report.json` | `assignments` 直接读它 |

**不在本项目内（有意为之）**

- `%USERPROFILE%\.dsh\skills\`：DSH 只从这个目录发现技能，源文件在这边、装过去就行。
- `~/.wechat-cli/deps`（13 MB）：第三方预编译依赖，本机架构相关，重新 pip 装更稳。
- `C:\Users\Apple\Documents\WXWork\...\Data`：企业微信自己的加密库，只读解密，不搬。
- `%LOCALAPPDATA%\BrowserSkill\bin\bsk.exe`：浏览器插件自带，装插件时一起装。
- `D:\Workspace\_cx`（242 MB）：早期逆学习通 asar 的临时解包，已无用，可删。

## 装到一台新机器（或新 DSH）

前提：Windows 10/11 **x64**；Python ≥3.12（本项目在 `D:\Python\Python315\python.exe`，3.15.0rc2 上验过）；Node ≥20（本机 v24.19.0）；微信、企业微信、学习通三个客户端都已装好并登录过；有一份能用的滴答账号。

目标：`msgscan.cmd sources` 四条线全绿，`msgscan.cmd since` 能出消息，`msgscan.cmd assignments` 能列作业。

### 0. 先看这张表，确认要装什么

| 依赖 | 装到哪 | 谁需要 | 需要提权 |
| --- | --- | --- | --- |
| Python 3.12+ | 任意，路径写进 `scripts/msgscan.cmd` | 全部 | 否 |
| pycryptodome、numpy | 系统 Python | 企微线 | 否 |
| Node 20+ | 任意 | 学习通消息线、数你最灵 | 否 |
| wechat-cli-plus | `~/.wechat-cli` | 微信线 | 否 |
| Playwright Chromium | `tools/xxt/browsers` | 学习通作业线 | 否 |
| playwright-core | `tools/cxmcp/node_modules` | 学习通消息线 | 否 |
| bsk 守护进程 | `%LOCALAPPDATA%\BrowserSkill\bin\bsk.exe` | 数你最灵 | 否 |
| 企业微信库 key | `state/wecom/key.txt` | 企微线 | **是，一次 UAC** |

### 1. 落地目录

把整个 `msgpipe` 复制到 `D:\Workspace\msgpipe`（路径写死在各脚本里，换盘要全局替换，见第 8 步）。第三方大件可以不搬，按下面几节重建：`tools/xxt/browsers`、`tools/xxt/chaoxing-agent-cli-main/.venv`、`tools/cxmcp/node_modules`、`tools/cxmcp/user-profile`。

```bash
cd /d/Workspace/msgpipe && ./scripts/msgscan.cmd sources   # 这一步会报缺什么，照着后面补
```

### 2. Python 依赖（企微线要）

```bash
D:/Python/Python315/python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple pycryptodome numpy
```

`msgscan.py` 本身只用标准库，不需要别的包。

### 3. 微信线

1. 装 wechat-cli-plus 到 `~/.wechat-cli`：配置与密钥已快照在 `state\wechat\`，先 `./scripts/restore-wechat-cli.cmd` 还原，再装 deps；没有快照时才用 `syskuku/wechat-todo` 的安装器（`node bin/wechat-todo.js --skip-init`）。最后要有 `~/.wechat-cli/wxcli.cmd` 与 `all_keys.json`。
2. **必须重装 deps**：仓库自带的 `vendor/wechat-cli/deps` 是 **win_arm64** 轮子，x64 机器上 `import Crypto` 会报 `[WinError 193] 不是有效的 Win32 应用程序`。重装：

```bash
D:/Python/Python315/python.exe -m pip install --target ~/.wechat-cli/deps --upgrade \
  pycryptodome psutil click zstandard -i https://mirrors.aliyun.com/pypi/simple
```

`zstandard` 没有对应 cp 版本的轮子时会现场编译，需要 VS2022 C++ 生成工具。

3. 提密钥：**微信必须在运行**，然后

```bash
cd /c/Users/Apple/.wechat-cli && ./wxcli.cmd init      # 期望 18/18 库密钥成功
./wxcli.cmd sessions --limit 5                         # 能列出会话即通
```

4. 装 `wechat-local` 技能（提供 `search_all.py`，msgscan 的微信分支 import 它）：

```bash
# SKILL.md 放 C:\Users\Apple\.dsh\skills\wechat-local\，脚本在 scripts\
```

### 4. 企业微信线

```bash
cd /d/Workspace/msgpipe/tools/wecom
D:/Python/Python315/python.exe wecom.py info            # 先看能不能读到库
```

读不到就抓 key（会弹一次 UAC）：

```bash
D:/Python/Python315/python.exe find_key.py              # 自动找 message.db，扫 WXWork.exe 内存
```

成功后把 32 位十六进制 key 写进 `state/wecom/key.txt`，再 `wecom.py refresh` 解密到 `state/wecom/cache\`。企业微信升级后 key 会变，重跑 `find_key.py` 即可。

### 5. 学习通 · 作业线

```bash
cd /d/Workspace/msgpipe/tools/xxt/chaoxing-agent-cli-main
D:/Python/Python315/python.exe -m venv .venv
.venv/Scripts/python.exe -m pip install -e . -i https://mirrors.aliyun.com/pypi/simple
```

装 Chromium（**不要装到用户目录**，本机 AppData 写入会被拦成 EPERM）：

```bash
export TEMP=/d/Workspace/msgpipe/tools/xxt/tmp TMP=/d/Workspace/msgpipe/tools/xxt/tmp
export PLAYWRIGHT_BROWSERS_PATH=/d/Workspace/msgpipe/tools/xxt/browsers
export PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
.venv/Scripts/python.exe -m playwright install chromium
```

改一处源码（不换就用不了）：`src/xxt_cli/browser.py` 第 7 行 `HOME`，默认的 `i.chaoxing.com` 是个人门户、没有课程卡片，会一直超时：

```python
HOME = "https://mooc1.chaoxing.com/visit/interaction"
```

登录（会开可见浏览器，扫码）：

```bash
cd /d/Workspace/msgpipe/tools/xxt && ./xxt.cmd auth --headed    # 登录态落到 state/xxt
./xxt.cmd courses                                              # 期望列出 14 门课
```

### 6. 学习通 · 消息线

```bash
cd /d/Workspace/msgpipe/tools/cxmcp
npm install                      # 只装 playwright-core，不下载浏览器
```

它会用系统 Edge/Chrome 的持久化 profile（`user-profile`）。**不要用手机号密码登录**，改成把学习通网页登录态灌进去：

```bash
# 用 tools/xxt 的 .venv 跑：从 state/xxt 读 storage_state，add_cookies 到 tools/cxmcp/user-profile
# 关键：storage_state 里会话级 cookie 的 expires=-1，必须改成 int(time.time())+365*86400，否则关浏览器就丢
D:/Python/Python315/python.exe - <<'EOF'
# 见 docs/消息来源.md 「灌 cookie」一段的完整脚本
EOF
```

然后确认：

```bash
node ./src/cli.mjs probe        # 期望 {"status":true,"msg":true}
```

打一个补丁（不改就没「消息」入口）：`src/chaoxing.mjs` 里 `openMessages()` 不要去找菜单项（默认门户是图书馆空间，找不到「消息」），直接跳 IM：

```js
const WEBIM_URL = 'https://fe.chaoxing.com/front/webim';
async function openMessages(page) { await page.goto(WEBIM_URL, {waitUntil:'domcontentloaded'});
  await page.waitForSelector('.message-list', {timeout:60000}); return page.mainFrame(); }
```

`dump.mjs` 是给 msgscan 用的薄封装（输出 `{time,conv,sender,kind,text}`），结尾必须有 `process.exit(0)`，否则 node 不退出。

### 7. 数你最灵（smartestu）

需要三样：browser-skill 的守护进程、Edge 里已登录的 `smartestu.cn` 会话、`bsk.exe` 在 `%LOCALAPPDATA%\BrowserSkill\bin\`。

```bash
export BSK_AUTO_START=0
"$LOCALAPPDATA/BrowserSkill/bin/bsk.exe" daemon start --foreground   # 必须常驻；前台跑在后台任务里
"$LOCALAPPDATA/BrowserSkill/bin/bsk.exe" status --json               # 期望列出 edge 实例、version_skew 可能为 true
```

第一次要先在 Edge 里手动登录一次 `https://smartestu.cn/assignment`，之后 `assignments` 复用这个登录态，每轮开一个 `--focus` 可见窗口读完即关。

### 8. 接到 DSH

1. **技能目录**（DSH 只从这发现技能）：三个技能已经打包在 `skills\` 里，一条命令装好——

```bash
./scripts/install-skills.cmd      # 复制 skills\{wechat-todo,wechat-local,wecom-local} 到 %USERPROFILE%\.dsh\skills
```

之后改技能只改 `skills\` 里的，再跑一次这个脚本；别直接改用户目录，会被覆盖。`wechat-todo\scripts\msgscan.cmd` 只是个转发器，逻辑全在项目里：

```bat
@echo off
call "D:\Workspace\msgpipe\scripts\msgscan.cmd" %*
```

2. **滴答 MCP**（整条待办链路唯一的必装 MCP，`msgscan` 自己不用它，是 AI 建任务时用的）

   **2.1 拿令牌**：浏览器打开 `https://developer.dida365.com`，用滴答账号登录，在「应用」里创建 / 打开一个应用，找到「个人访问令牌 / Access Token」，复制那串 `dp_` 开头的字符串（页面措辞可能变，认 `dp_` 前缀即可）。令牌等同密码，**别贴进公开仓库**，本项目只把它写在本机 profile 里。

   **2.2 先验证令牌**（省得后面在 DSH 里排错）：

```bash
curl -s --ssl-no-revoke -X POST https://mcp.dida365.com \
  -H "Authorization: Bearer dp_你的令牌" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

   期望返回里有 `"serverInfo":{"name":"TickTick MCP Server"}`。返回 `401` 与 `Bearer error="invalid_token"` 就是令牌不对或过期。注意 `https://mcp.dida365.com/mcp` 是 404，正确地址是根路径。

   **2.3 写进 profile**：最省事是 `./scripts/install-mcp.cmd`（先把令牌写进 `state\dsh\dida-token.txt`；不带 `--apply` 只干跑，已装过会跳过）。手动做法是先备份，再在 `C:\Users\Apple\.dsh\profiles\web\cordis.patch.yml` **末尾**追加（注意是顶层列表项，`- insert:` 前面不能有缩进）：

```yaml
- insert:
    - id: mcp-dida365
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: dida365
        transport: streamable-http
        url: https://mcp.dida365.com
        headers:
          Authorization: 'Bearer dp_你的令牌'
```

```bash
cp ~/.dsh/profiles/web/cordis.patch.yml ~/.dsh/profiles/web/cordis.patch.yml.bak-$(date +%Y%m%d-%H%M%S)
```

   **2.4 生效与验收**：profile 是 `patchReload: live`，保存即热加载，不用重启。新开或继续对话后，工具列表里应出现 58 个 `mcp__dida365__*`（`list_projects`、`create_task`、`filter_tasks`、`batch_add_tasks`、`update_task`、`complete_task` 等）。第一句先跑 `list_projects`，能返回「👋欢迎」与 `inbox` 就是通了；用 `filter_tasks` 带 `{"status":[0]}` 看未完成任务。

   **2.5 排错**

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 工具没出现 | YAML 缩进错 / `- insert:` 被缩进 / 上一项少了 `-` | `node -e "import('node:fs')"` 不用试，直接看 yml 结构：每个顶层项以 `- ` 开头，同级对齐 |
| 出现但一调就 401 | 令牌过期、多了空格、用了 `Bearer ` 两次 | 重跑 2.2 验证，头里只写一次 `Bearer ` |
| 出现两个同名 server | 重复追加了 insert 块 | 删掉多余块，只留一个 `id: mcp-dida365` |
| 改完没反应 | 编辑时 profile 正在被写，热加载失败 | 保存后再改一个无关字符触发一次，或重启 `dsh web` |
| `inbox` 建的任务找不到 | 服务端把 `projectId: "inbox"` 回写成 `inbox1029312273` | 后续查改都用回写后的 id |

   **2.6 换令牌 / 移除**：换令牌只改 `Authorization` 那一行；移除就整段删掉 `- insert:` 块，热加载后 `mcp__dida365__*` 消失。删除不影响已经建好的任务（任务在滴答云端）。

3. 换过盘符或用户名时，全局改这些写死的路径：`scripts/msgscan.py` 的 `PROJ/STATE_DIR/WECOM_SCRIPTS/XXT_*`、`scripts/msgscan.cmd` 的解释器、`tools/xxt/xxt.cmd` 四个变量、`tools/wecom/wecom.py` 的 HOME 与缓存目录、`tools/xxt/scan_all.py` 的报告路径、`tools/cxmcp/dump.mjs` 的输出目录。

### 9. 验收

```bash
cd /d/Workspace/msgpipe
./scripts/msgscan.cmd sources              # 期望 wechat/wecom/chaoxing 都 OK + xxt 报告在位
./scripts/msgscan.cmd since --limit 5      # 期望出消息行
./scripts/msgscan.cmd assignments          # 期望学习通作业表 + 数你最灵作业表
./scripts/msgscan.cmd advance --at "2026-11-16 00:00"   # 最后才推水位
```

然后让 AI 跑一轮「更新待办」：应当生成 `待办\日期纪要\<今天>.md`、更新今日待办与待办总表、在滴答里建/改任务，最后汇报「新建 N / 勾掉 M / 排除重复 K」。

### 10. 装的时候最容易卡住的六件事

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `CRYPT_E_NO_REVOCATION_CHECK (0x80092012)` | schannel 吊销检查失败 | curl 加 `--ssl-no-revoke`；git 用 `GIT_SSL_NO_VERIFY=true` |
| `[WinError 193] 不是有效的 Win32 应用程序` | 预编译依赖是 win_arm64 | 用本机 Python 重装 `~/.wechat-cli/deps` |
| `mkdir ... EPERM` | Playwright 往 AppData 写被拦 | 把 `TEMP/TMP` 和 `PLAYWRIGHT_BROWSERS_PATH` 指到项目内 |
| `LOGIN_TIMEOUT` / `PAGE_UNRECOGNIZED` | 学习通 HOME 是个人门户 | 改 `browser.py` 为 `mooc1.chaoxing.com/visit/interaction` |
| `could not start daemon ... Job Object breakaway` | bsk 无法自己起守护进程 | `bsk daemon start --foreground` 放进常驻后台任务，并 `BSK_AUTO_START=0` |
| msgscan 卡 300 秒超时 | 子进程 stdin 管道没关 | 调 `dump.mjs` 时加 `stdin=subprocess.DEVNULL`，脚本内 `process.exit(0)` |

## 维护提示

- 换机器 / 微信升级：先修 `~/.wechat-cli`（见 `docs/消息来源.md`）。
- 企微换 key：`tools/wecom/find_key.py` 扫描（需一次 UAC），把 key 写进 `state/wecom/key.txt`。
- 学习通登录过期：`tools/xxt/xxt.cmd auth --headed` 重新扫码，登录态落在 `state/xxt`。
- 数你最灵：需要 bsk 守护进程（`bsk daemon start --foreground`）与 Edge 里已登录的会话。
- 改完任何脚本，跑一遍 `msgscan sources` 与 `msgscan since --limit 3` 再收工。
