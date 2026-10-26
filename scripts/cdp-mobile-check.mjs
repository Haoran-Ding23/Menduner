/**
 * F08 移动端补测：390×844 下切到「地图」视图，确认地图渲染、再切回列表不丢筛选。
 *
 * 单独成文件，避免和桌面测量脚本互相牵连（那次把模板字符串写进 node 脚本，
 * 被 ${} 插值吃掉，脚本直接跑不起来）。
 *
 * 用法：node scripts/cdp-mobile-check.mjs https://entgroup14.com
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = process.argv[3] ?? "http://127.0.0.1:9345";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗：超时"); process.exit(2); }, 90000);

const PROBE = [
  '(function () {',
  '  var all = Array.prototype.slice.call(document.querySelectorAll("button, [role=\\"radio\\"], label, div"));',
  '  function byText(t) {',
  '    for (var i = all.length - 1; i >= 0; i--) { if ((all[i].innerText || "").trim() === t) return all[i]; }',
  '    return null;',
  '  }',
  '  var entry = byText("地图");',
  '  var listOnly = !!document.querySelector(".event-list");',
  '  var mapHidden = !document.querySelector(".map-shell");',
  '  if (!entry) return Promise.resolve({ entryVisible: false, listOnly: listOnly, mapHidden: mapHidden });',
  '  entry.click();',
  '  return new Promise(function (resolve) {',
  '    setTimeout(function () {',
  '      var el = document.querySelector(".map-shell");',
  '      var rect = el ? el.getBoundingClientRect() : null;',
  '      var back = byText("活动列表");',
  '      if (back) back.click();',
  '      setTimeout(function () {',
  '        resolve({',
  '          entryVisible: true,',
  '          mapHeight: rect ? Math.round(rect.height) : 0,',
  '          mapHasSize: rect ? rect.height > 100 : false,',
  '          listBack: !!document.querySelector(".event-list"),',
  '          monthsCollapsed: !document.querySelector(".months"),',
  '        });',
  '      }, 900);',
  '    }, 1800);',
  '  });',
  '})()',
].join("\n");

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
      const t = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 20000);
      pending.set(mid, {
        resolve: (v) => { clearTimeout(t); resolve(v); },
        reject: (e) => { clearTimeout(t); reject(e); },
      });
      socket.send(JSON.stringify({ id: mid, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await send("Page.navigate", { url: BASE + "/map" });
  await sleep(4500);
  const result = await send("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: true });
  const value = result.result ? result.result.value : null;
  console.log("  移动端补测结果:", JSON.stringify(value));
  const ok = value && value.entryVisible && value.mapHasSize && value.listBack;
  console.log(ok ? "[PASS] 切换入口可见、地图渲染有高度、切回列表正常" : "[FAIL] 见上");
  await send("Emulation.clearDeviceMetricsOverride");
  socket.close();
  clearTimeout(WATCHDOG);
  process.exitCode = ok ? 0 : 1;
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exitCode = 1; });
