/**
 * 移动端逐页验收（GPT Round 25 第 3 轮要求）：390×844 下检查
 * 1) 是否出现横向溢出（横向滚动条）；
 * 2) 主要区块是否渲染（标题存在）；
 * 3) 是否有可点的空状态引导（.empty-hint）。
 *
 * node scripts/cdp-mobile-audit.mjs https://entgroup14.com
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = "http://127.0.0.1:9345";
const PAGES = [
  ["/", "首页"],
  ["/workbench", "本店工作台"],
  ["/map", "城市活动地图"],
  ["/agenda", "活动清单"],
  ["/insights", "商圈洞察"],
  ["/graph", "知识图谱"],
  ["/evidence", "数据质量与来源"],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗超时"); process.exit(2); }, 240000);

const PROBE = [
  '(function () {',
  '  var doc = document.documentElement;',
  '  var h1 = document.querySelector("h1");',
  '  return {',
  '    overflowX: doc.scrollWidth - doc.clientWidth,',
  '    heading: h1 ? h1.textContent.trim().slice(0, 18) : null,',
  '    hints: document.querySelectorAll(".empty-hint").length,',
  '    width: window.innerWidth',
  '  };',
  '})()',
].join("\n");

async function main() {
  const list = await (await fetch(`${DEBUG}/json/list`)).json();
  const page = list.filter((p) => p.type === "page")[0];
  if (!page) throw new Error("没有页面目标");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve);
    ws.addEventListener("error", () => reject(new Error("WS 失败")));
  });
  ws.addEventListener("message", async (event) => {
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
      ws.send(JSON.stringify({ id: mid, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });

  const rows = [];
  for (const [path, name] of PAGES) {
    await send("Page.navigate", { url: BASE + path });
    await sleep(6000);
    const result = await send("Runtime.evaluate", { expression: PROBE, returnByValue: true });
    const value = (result.result && result.result.value) || {};
    rows.push({ 页面: name, 路径: path, ...value });
  }

  console.table(rows);
  const bad = rows.filter((row) => (row.overflowX ?? 0) > 2 || !row.heading);
  console.log(
    bad.length === 0
      ? "\n[PASS] 390×844 下所有页面无横向溢出且有主标题"
      : "\n[FAIL] 存在问题页面：" + JSON.stringify(bad),
  );
  ws.close();
  clearTimeout(WATCHDOG);
  process.exitCode = bad.length === 0 ? 0 : 1;
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exit(1); });
