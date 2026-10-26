/**
 * 通用截图：node scripts/cdp-shot.mjs <url> <out.png> [width] [height]
 * 用 CDP 直接抓整页，避免渲染器缩放问题。
 */
const url = process.argv[2] ?? "https://entgroup14.com/insights";
const out = process.argv[3] ?? "deliverables/shot.png";
const width = Number(process.argv[4] ?? 1440);
const height = Number(process.argv[5] ?? 1000);
const DEBUG = process.argv[6] ?? "http://127.0.0.1:9345";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WAIT_MS = Number(process.env.SHOT_WAIT ?? 18000);
const WATCHDOG = setTimeout(() => { console.error("看门狗超时"); process.exit(2); }, 120000);

async function main() {
  const list = await (await fetch(`${DEBUG}/json/list`)).json();
  const page = list.filter((p) => p.type === "page")[0];
  if (!page) throw new Error("没有页面目标");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve);
    socket.addEventListener("error", () => reject(new Error("WS 失败")));
  });
  socket.addEventListener("message", async (event) => {
    let raw;
    if (typeof event.data === "string") raw = event.data;
    else if (event.data instanceof Blob) raw = await event.data.text();
    else raw = Buffer.from(event.data).toString("utf8");
    const msg = JSON.parse(raw);
    const entry = msg.id ? pending.get(msg.id) : null;
    if (!entry) return;
    pending.delete(msg.id);
    msg.error ? entry.reject(new Error(msg.error.message)) : entry.resolve(msg.result);
  });
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const mid = ++id;
      const t = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 30000);
      pending.set(mid, { resolve: (v) => { clearTimeout(t); resolve(v); }, reject: (e) => { clearTimeout(t); reject(e); } });
      socket.send(JSON.stringify({ id: mid, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url });
  await sleep(WAIT_MS);
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const probe = await send(Runtime.evaluate, {
      expression: document.querySelectorAll(\canvas\).length,
      returnByValue: true,
    });
    if ((probe.result && probe.result.value) >= 3) break;
    await sleep(2000);
  }
  // 整页高度
  const metrics = await send("Page.getLayoutMetrics");
  const content = metrics.cssContentSize ?? metrics.contentSize ?? { width, height };
  const shot = await send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width, height: Math.min(Math.ceil(content.height), 4000), scale: 1 },
  });
  const { writeFileSync, mkdirSync } = await import("node:fs");
  const { dirname } = await import("node:path");
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, Buffer.from(shot.data, "base64"));
  console.log("  已保存:", out, "| 页面高:", Math.round(content.height));
  await send("Emulation.clearDeviceMetricsOverride");
  socket.close();
  clearTimeout(WATCHDOG);
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exit(1); });
