/**
 * 验证 mcp server 能否在本机启动并完成 MCP 握手。
 *
 * 目的：在写进 cordis.patch.yml 之前，先用真实子进程跑一遍 —— 配置是否生效是重启之后的
 * 事，但「npx 能不能拉起 chrome-devtools-mcp」「--autoConnect 能不能连上当前 Chrome」
 * 现在就能验证，避免把失败配置交给用户去重启。
 *
 * 只做 initialize + tools/list，不调用任何会改动 Chrome 的工具。
 */
import { spawn } from "node:child_process";

const COMMAND = process.env.MCP_COMMAND ?? "npx";
const ARGS = [
  "-y",
  "chrome-devtools-mcp@latest",
  "--autoConnect",
  ...(process.env.MCP_EXTRA_ARGS ? process.env.MCP_EXTRA_ARGS.split(" ") : []),
];

const child = spawn(COMMAND, ARGS, {
  shell: true,
  stdio: ["pipe", "pipe", "pipe"],
  windowsHide: true,
});

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
child.stderr.on("data", (chunk) => {
  stderr += chunk.toString("utf8");
});

const send = (payload) => child.stdin.write(JSON.stringify(payload) + "\n");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const main = async () => {
  // 给 npx 下载/解析包的时间
  await wait(Number(process.env.MCP_STARTUP_MS ?? 12000));

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
  await wait(6000);

  send({ jsonrpc: "2.0", method: "notifications/initialized", params: {} });
  send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
  await wait(8000);

  const init = messages.find((message) => message.id === 1);
  const tools = messages.find((message) => message.id === 2);

  console.log("=== initialize 响应 ===");
  if (init) {
    const info = init.result?.serverInfo ?? {};
    console.log("  serverInfo:", JSON.stringify(info));
    console.log("  protocolVersion:", init.result?.protocolVersion ?? "(none)");
    if (init.error) console.log("  error:", JSON.stringify(init.error));
  } else {
    console.log("  (没有收到 initialize 响应)");
  }

  console.log("=== tools/list 响应 ===");
  const names = (tools?.result?.tools ?? []).map((tool) => tool.name);
  if (names.length) {
    console.log("  工具数量:", names.length);
    console.log("  工具名:", names.slice(0, 30).join(", "));
  } else {
    console.log("  (没有拿到工具列表)");
    if (tools?.error) console.log("  error:", JSON.stringify(tools.error));
  }

  if (stderr.trim()) {
    console.log("=== stderr（前 1200 字符）===");
    console.log(stderr.trim().slice(0, 1200));
  }

  child.kill();
  const ok = !!init?.result && names.length > 0;
  console.log(ok ? "\n[PASS] MCP 握手成功" : "\n[FAIL] MCP 握手未完成");
  process.exitCode = ok ? 0 : 1;
};

main().catch((error) => {
  console.error("脚本失败:", error.message);
  child.kill();
  process.exitCode = 1;
});
