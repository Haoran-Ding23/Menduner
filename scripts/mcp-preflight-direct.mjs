/**
 * 验证「直接用 node 解释器 + 包内入口」能否在 shell:false 下启动 MCP 服务器。
 *
 * 背景：Node 20+ 在 Windows 上禁止 spawn .cmd/.bat（EINVAL），所以配置里的 command 不能写 npx。
 * 这里用 dsh 运行时自带的 node.exe 直接跑 chrome-devtools-mcp 的入口文件，并完成 MCP 握手，
 * 证明配置里要写的那条命令是真实可用的。
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const RUNTIME_NODE = join(
  homedir(),
  ".dsh",
  "dsh-runtimes",
  "dsh-primary-runtime",
  "dependencies",
  "node",
  "bin",
  "node.exe",
);
const ENTRY = join(
  homedir(),
  ".dsh",
  "profiles",
  "desktop",
  "node_modules",
  "chrome-devtools-mcp",
  "build",
  "src",
  "bin",
  "chrome-devtools-mcp.js",
);

console.log("  node 解释器:", RUNTIME_NODE, existsSync(RUNTIME_NODE) ? "(存在)" : "(缺失)");
console.log("  MCP 入口  :", ENTRY, existsSync(ENTRY) ? "(存在)" : "(缺失)");
if (!existsSync(RUNTIME_NODE) || !existsSync(ENTRY)) {
  console.log("\n[FAIL] 缺少可执行文件或入口");
  process.exit(1);
}

const child = spawn(
  RUNTIME_NODE,
  [ENTRY, "--autoConnect", "--no-usage-statistics", "--no-performance-crux"],
  { shell: false, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] },
);

let buffer = "";
const messages = [];
child.stdout.on("data", (chunk) => {
  buffer += chunk.toString("utf8");
  let index;
  while ((index = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, index).trim();
    buffer = buffer.slice(index + 1);
    if (!line) continue;
    try {
      messages.push(JSON.parse(line));
    } catch {
      messages.push({ raw: line });
    }
  }
});
let stderr = "";
child.stderr.on("data", (chunk) => (stderr += chunk.toString("utf8")));
child.on("error", (error) => console.log("  spawn error:", error.code || error.message));

const send = (payload) => child.stdin.write(JSON.stringify(payload) + "\n");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const main = async () => {
  await wait(4000);
  send({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "dsh-preflight", version: "0.0.1" },
    },
  });
  await wait(5000);
  send({ jsonrpc: "2.0", method: "notifications/initialized", params: {} });
  send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
  await wait(6000);

  const init = messages.find((message) => message.id === 1);
  const tools = messages.find((message) => message.id === 2);
  const names = (tools?.result?.tools ?? []).map((tool) => tool.name);

  console.log("  serverInfo:", JSON.stringify(init?.result?.serverInfo ?? null));
  console.log("  工具数量:", names.length);
  console.log("  含 list_pages:", names.includes("list_pages"), "| select_page:", names.includes("select_page"), "| take_snapshot:", names.includes("take_snapshot"));
  if (stderr.trim()) console.log("  stderr 片段:", stderr.trim().replace(/\s+/g, " ").slice(0, 260));

  child.kill();
  const ok = !!init?.result && names.length > 0;
  console.log(ok ? "\n[PASS] 配置里要写的命令真实可用" : "\n[FAIL] 握手未完成");
  process.exitCode = ok ? 0 : 1;
};

main().catch((error) => {
  console.error("脚本失败:", error.message);
  child.kill();
  process.exitCode = 1;
});
