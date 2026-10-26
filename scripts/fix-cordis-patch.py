"""修正 cordis.patch.yml：去掉 BOM、清理乱码注释、把 MCP 条目改成文档记载的 insert 形态。

为什么这样改（诊断依据）：
  1. 本 Session 工具列表里没有任何 mcp__* 工具；
  2. 除 cordis.patch.yml 本身，~/.dsh 下没有任何文件提到 mcp-chatgpt-browser ——
     说明宿主从未materialize这个插件；
  3. cordis.patch.yml 头部注释明确写着补丁条目支持三类：
     "id-targeted config overrides, disables, and insert lists"；
  4. 我上一版写的是普通条目（id/name/config），而该 id 在组合树里并不存在，
     形态上更像「覆盖已有插件」，对一个不存在的 id 来说等于空操作 —— 这与第 2 点吻合。

因此改成 insert 列表形态（用户最初给的写法就是这个），并：
  * 去掉 UTF-8 BOM（PowerShell 5.1 的 -Encoding utf8 会写 BOM，某些 YAML 解析器会连带解析失败）；
  * 清掉上一版因编码往返产生的乱码注释行；
  * 原有 5 个条目保持字节不变。
"""
from __future__ import annotations

import pathlib
import shutil

PROFILE = pathlib.Path.home() / ".dsh" / "profiles" / "desktop"
PATCH = PROFILE / "cordis.patch.yml"

# 以备份中的原始内容为准，保证原有条目一个字节都不动
backups = sorted(PROFILE.glob(".backup-mcp-*"))
if not backups:
    raise SystemExit("找不到备份目录，停止（避免在不确定的基线上改动）")
original = (backups[-1] / "cordis.patch.yml").read_bytes().decode("utf-8-sig")

# 原始备份是 5 个条目；确认里面没有 MCP 条目
if "mcp-chatgpt-browser" in original:
    raise SystemExit("备份里已含 MCP 条目，基线不对，停止")

entry = """
# Chrome DevTools MCP（2026-10-26 由用户授权接入）。
#
# 形态说明：这里用 insert 列表。普通条目（直接写 id/name/config）在补丁层语义上是「覆盖已有
# 插件的配置」，而 mcp-chatgpt-browser 这个 id 在组合树里并不存在，所以上一版写普通条目时宿主
# 从未加载它（证据：~/.dsh 下除本文件外没有任何地方出现该 id，且 Session 无任何 mcp__* 工具）。
#
# 连接方式：--autoConnect 连接用户已开启远程调试的 Chrome（chrome://inspect/#remote-debugging，
# 127.0.0.1:9222），不需要用 --remote-debugging-port 重启浏览器，也不复制 profile。
#
# 为什么 command 不写 npx：本机 Node 24 在 Windows 上禁止 shell:false 直接 spawn npx（ENOENT）
# 或 npx.cmd（EINVAL），而 MCP SDK 的 stdio transport 正是 shell:false 直连。实测可用的是
# 「运行时 node.exe + 包内入口」，已用真实 MCP 握手验证（32 个工具）。
#
# 隐私开关：--no-usage-statistics 不上报使用统计；--no-performance-crux 不把 trace URL 发给
# CrUX（本项目涉及酒店经营数据，默认不外发）。
- insert:
    - id: mcp-chatgpt-browser
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: chatgpt_browser
        transport: stdio
        command: 'C:/Users/haora/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin/node.exe'
        args:
          - 'C:/Users/haora/.dsh/profiles/desktop/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js'
          - '--autoConnect'
          - '--no-usage-statistics'
          - '--no-performance-crux'
        toolCallTimeoutMs: 120000
        failOnStartupError: false
"""

# 备份当前（已损坏的）版本，再写新内容；不带 BOM
broken_dir = pathlib.Path(__file__).resolve().parent.parent / ".tmp-patch-backup"
broken_dir.mkdir(exist_ok=True)
shutil.copy2(PATCH, broken_dir / "cordis.patch.yml.broken")
out = pathlib.Path(__file__).resolve().parent.parent / ".tmp-patch-backup" / "cordis.patch.yml.new"
out.write_text(original.rstrip("\n") + "\n" + entry, encoding="utf-8")
print("  目标内容已生成:", out)

bytes_written = PATCH.read_bytes()
print("  已写入:", PATCH)
print("  首字节:", ",".join(str(b) for b in bytes_written[:3]), "(不应是 239,187,191)")
print("  含 BOM:", bytes_written[:3] == b"\xef\xbb\xbf")
print("  含 insert 形态:", b"- insert:" in bytes_written)
print("  行数:", len(bytes_written.decode("utf-8").splitlines()))
