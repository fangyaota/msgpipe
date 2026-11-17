# 第三方来源

本目录下的工具是从上游项目修改而来，遵循各自许可证。修改点写在各自 README 或本文件里。

| 目录 | 上游 | 许可证 | 本仓库的改动 |
| --- | --- | --- | --- |
| `xxt/chaoxing-agent-cli-main` | [PYFGDUF/chaoxing-agent-cli](https://github.com/PYFGDUF/chaoxing-agent-cli) | MIT（见其 LICENSE） | `src/xxt_cli/browser.py` 的 HOME 改为 `https://mooc1.chaoxing.com/visit/interaction`（默认门户没有课程卡片，会登录校验超时）；新增 `scan_all.py` 全课程巡检 |
| `cxmcp` | [XueQian17654/ChaoXingMessageMCP](https://github.com/XueQian17654/ChaoXingMessageMCP) | MIT（见其 LICENSE） | `src/chaoxing.mjs` 的 `openMessages()` 改为直接打开 `https://fe.chaoxing.com/front/webim`；新增 `dump.mjs` 统一输出 |
| `wechat-cli/` | [maomao3334/wechat-cli-plus](https://github.com/maomao3334/wechat-cli-plus) | Apache-2.0（见其 LICENSE） | **源码未改**（37 个文件与上游 0.2.4 的 vendor 副本逐字节一致）；只把它自带的 `deps` 从 win_arm64 轮子换成本机 x64 的（见 README 第 3 步） |
| `wecom` | [freanocank/wecom-agent](https://github.com/freanocank/wecom-agent) | MIT | 取 `decrypt/windows/` 与解密模块；`wecom.py`、`find_key.py` 由本仓库改写为技能 CLI（内存扫描改为 8 字节对齐的 numpy 预筛） |

`skills/wechat-local` 与 `skills/wecom-local` 里的 `search_all.py`、`wecom.py` 同样源自上述项目。

微信线用的 [wechat-cli-plus](https://github.com/maomao3334/wechat-cli-plus)（Apache-2.0）不随本仓库分发，按 README 第 3 步安装。

### 我们在快照上加的（原代码未改）

- `wechat_cli/core/datimg.py`、`wechat_cli/commands/images.py`：新增 `wechat-cli images` 子命令，
  用于解密微信 4.x 的图片 `.dat`（V2 格式：AES-128-ECB 段 + 明文段 + 单字节 XOR 段）。
  算法取自 [ZedeX/weixin-decrypte-script](https://github.com/ZedeX/weixin-decrypte-script)（MIT），精简重写。
  改动仅在 `wechat_cli/main.py` 里加了一行 import 与一行 `cli.add_command(images)`。
