/**
 * F08 首屏密度验证：在三种视口下量地图在首屏内的可见高度占比，并检查横向溢出。
 *
 * 为什么必须实测：GPT 的三条验收里第一条是「1440×900 下地图可见高度 ≥ 视口 40%（360px）」，
 * 这是几何事实，只能从真实渲染里量，不能靠读 CSS 推断。
 *
 * 用法（先用 --remote-debugging-port 启动 Chrome，并有一个 preview 服务在跑）：
 *   node scripts/cdp-layout-check.mjs http://127.0.0.1:5299
 */
const BASE = process.argv[2] ?? "http://127.0.0.1:5299";
const DEBUG = process.argv[3] ?? "http://127.0.0.1:9345";

const VIEWPORTS = [
  { name: "1440x900", width: 1440, height: 900, mobile: false },
  { name: "1280x720", width: 1280, height: 720, mobile: false },
  { name: "390x844", width: 390, height: 844, mobile: true },
];

const WATCHDOG = setTimeout(() => {
  console.error("看门狗：超过 120 秒未完成");
  process.exit(2);
}, 120000);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function firstPage() {
  const res = await fetch(`${DEBUG}/json/list`);
  const pages = (await res.json()).filter((p) => p.type === "page");
  if (!pages.length) throw new Error("没有页面目标");
  return pages[0];
}

function connect(url) {
  const socket = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  const ready = new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("WS 握手超时")), 10000);
    socket.addEventListener("open", () => { clearTimeout(t); resolve(); });
    socket.addEventListener("error", () => { clearTimeout(t); reject(new Error("WS 连接失败")); });
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
      const t = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 20000);
      pending.set(mid, {
        resolve: (v) => { clearTimeout(t); resolve(v); },
        reject: (e) => { clearTimeout(t); reject(e); },
      });
      socket.send(JSON.stringify({ id: mid, method, params }));
    });
  return { ready, send, close: () => socket.close() };
}

const MEASURE = `
(() => {
  const map = document.querySelector('.map-shell') || document.querySelector('.map-panel');
  const rect = map ? map.getBoundingClientRect() : null;
  const doc = document.documentElement;
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    mapTop: rect ? Math.round(rect.top) : null,
    mapHeight: rect ? Math.round(rect.height) : null,
    visible: rect ? Math.max(0, Math.round(Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0))) : 0,
    overflowX: doc.scrollWidth - doc.clientWidth,
    monthsCollapsed: !document.querySelector('.months'),
  };
})()`;

async function main() {
  const page = await firstPage();
  const client = connect(page.webSocketDebuggerUrl);
  await client.ready;
  await client.send("Page.enable");
  await client.send("Runtime.enable");

  const rows = [];
  for (const vp of VIEWPORTS) {
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: vp.width, height: vp.height, deviceScaleFactor: 1, mobile: vp.mobile,
    });
    await client.send("Page.navigate", { url: `${BASE}/map` });
    for (let i = 0; i < 40; i += 1) {
      await sleep(300);
      const r = await client.send("Runtime.evaluate", { expression: MEASURE, returnByValue: true });
      const v = r.result?.value;
      if (v && v.mapHeight) { rows.push({ 视口: vp.name, ...v, ratio: +(v.visible / v.viewport.h).toFixed(3) }); break; }
    }
  }
  await client.send("Emulation.clearDeviceMetricsOverride");
  client.close();

  console.table(rows);
  const desktop = rows.find((r) => r.视口 === "1440x900");
  const ok = desktop && desktop.ratio >= 0.4 && rows.every((r) => r.overflowX <= 0);
  console.log(ok ? "\n[PASS] F08 首屏：地图可见高度达标且无横向溢出" : "\n[FAIL] F08：见上表");
  process.exitCode = ok ? 0 : 1;
}

main().then(() => clearTimeout(WATCHDOG)).catch((e) => {
  clearTimeout(WATCHDOG);
  console.error("脚本失败:", e.message);
  process.exitCode = 1;
});
