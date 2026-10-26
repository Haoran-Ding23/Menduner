/**
 * 判断 Windows 下不经过 shell 时，MCP 服务器应该用 `npx` 还是 `npx.cmd`。
 *
 * 为什么要单独测：cordis 配置里的 command 会被 MCP SDK 的 StdioClientTransport 直接 spawn，
 * 而 PowerShell 里能跑 `npx` 不代表 Node 的 spawn（shell:false）能跑 —— Windows 上 npx 实际是
 * npx.cmd，直接 spawn 会 ENOENT。这里两种都试一遍，用真实结果决定配置写哪个。
 */
import { spawn } from "node:child_process";

const probe = (command) =>
  new Promise((resolve) => {
    const child = spawn(command, ["--version"], { shell: false, windowsHide: true });
    let out = "";
    let err = "";
    child.stdout.on("data", (chunk) => (out += chunk.toString()));
    child.stderr.on("data", (chunk) => (err += chunk.toString()));
    child.on("error", (error) => resolve({ command, ok: false, detail: error.code || error.message }));
    child.on("close", (code) =>
      resolve({ command, ok: code === 0, detail: (out || err).trim().split("\n")[0] || `exit ${code}` }),
    );
  });

const main = async () => {
  for (const command of ["npx", "npx.cmd"]) {
    const result = await probe(command);
    console.log(
      `  ${command.padEnd(8)} shell:false -> ${result.ok ? "OK" : "FAIL"}  ${result.detail}`,
    );
  }
};

main();
