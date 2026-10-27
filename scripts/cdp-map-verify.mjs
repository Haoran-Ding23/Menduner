/**
 * 验证地图是否真的定位到目标活动：读取 window.__mapFocus（Map 组件在居中时写入）。
 * node scripts/cdp-map-verify.mjs "https://entgroup14.com/map?event=<id>" [expectedLng] [expectedLat]
 */
const url = process.argv[2] ?? "https://entgroup14.com/map?event=evt-ded705d3a98fc9a4bf1043ae";
const expectLng = process.argv[3] ? Number(process.argv[3]) : null;
const expectLat = process.argv[4] ? Number(process.argv[4]) : null;
const DEBUG = "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗超时"); process.exit(2); }, 120000);

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
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url });

  let focus = null;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    await sleep(3000);
    const probe = await send("Runtime.evaluate", {
      expression: "window.__mapFocus ? JSON.stringify(window.__mapFocus) : null",
      returnByValue: true,
    });
    const value = probe.result ? probe.result.value : null;
    if (value) { focus = JSON.parse(value); break; }
  }
  const noticeProbe = await send("Runtime.evaluate", {
    expression: "(document.querySelector('.map-focus-notice')||{}).innerText || null",
    returnByValue: true,
  });
  const notice = noticeProbe.result ? noticeProbe.result.value : null;

  console.log("  window.__mapFocus:", JSON.stringify(focus));
  console.log("  提示条:", JSON.stringify(notice));
  let ok = Boolean(focus);
  if (ok && expectLng !== null && expectLat !== null) {
    const dLng = Math.abs(focus.lng - expectLng);
    const dLat = Math.abs(focus.lat - expectLat);
    ok = dLng < 0.0005 && dLat < 0.0005;
    console.log(`  期望坐标 ${expectLng},${expectLat}；偏差 lng=${dLng.toFixed(5)} lat=${dLat.toFixed(5)}`);
  }
  console.log(ok ? "[PASS] 地图已定位到目标活动坐标" : "[FAIL] 未定位");
  ws.close();
  clearTimeout(WATCHDOG);
  process.exitCode = ok ? 0 : 1;
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exit(1); });
