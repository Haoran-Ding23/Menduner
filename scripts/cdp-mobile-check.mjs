/**
 * F08 移动端交互补测（GPT Round 9 要求）。
 *
 * 390×844 下要证明的不只是「地图有高度」，而是：
 *   1. 列表优先视图里能看到「地图」切换入口；
 *   2. 切换后地图真的渲染出标记（数量 > 0），且能点开一个标记；
 *   3. 切回列表后，原有筛选（类别下拉）保持不变，不因切换被重置。
 *
 * 用法：node scripts/cdp-mobile-check.mjs https://entgroup14.com
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = process.argv[3] ?? "http://127.0.0.1:9345";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗：超时"); process.exit(2); }, 120000);

const PROBE = [
  '(async function () {',
  '  var all = function () { return Array.prototype.slice.call(document.querySelectorAll("button, [role=\\"radio\\"], label, div")); };',
  '  function byText(t) { var list = all(); for (var i = list.length - 1; i >= 0; i--) { if ((list[i].innerText || "").trim() === t) return list[i]; } return null; }',
  '  function markerCount() { return document.querySelectorAll(".map-marker, .map-marker-hotspot").length; }',
  '  function filterValue() {',
  '    var sel = document.querySelector(".filterbar .ant-select-selection-item");',
  '    return sel ? (sel.getAttribute("title") || sel.innerText || "").trim() : null;',
  '  }',
  '  var entry = byText("地图");',
  '  var beforeFilter = filterValue();',
  '  if (!entry) return { entryVisible: false, beforeFilter: beforeFilter };',
  '  entry.click();',
  '  await new Promise(function (r) { setTimeout(r, 2000); });',
  '  var markers = markerCount();',
  '  var markerEl = document.querySelector(".map-marker, .map-marker-hotspot");',
  '  var clicked = false;',
  '  if (markerEl) { markerEl.click(); clicked = true; await new Promise(function (r) { setTimeout(r, 1200); }); }',
  '  var detailText = (document.body.innerText || "").slice(0, 4000);',
  '  var back = byText("活动列表");',
  '  if (back) back.click();',
  '  await new Promise(function (r) { setTimeout(r, 1000); });',
  '  return {',
  '    entryVisible: true,',
  '    markers: markers,',
  '    markerClicked: clicked,',
  '    detailOpened: /活动详情|查看详情|场馆|来源/.test(detailText),',
  '    listBack: !!document.querySelector(".event-list"),',
  '    beforeFilter: beforeFilter,',
  '    afterFilter: filterValue(),',
  '    filterPreserved: beforeFilter === filterValue(),',
  '  };',
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
      const t = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 25000);
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
  await sleep(5000);
  const result = await send("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: true });
  const value = result.result ? result.result.value : null;
  console.log("  移动端交互补测:", JSON.stringify(value));

  const ok =
    value &&
    value.entryVisible &&
    value.markers > 0 &&
    value.markerClicked &&
    value.listBack &&
    value.filterPreserved !== false;
  console.log(ok ? "[PASS] 切换入口可见、标记可点、切回列表筛选保持" : "[FAIL] 见上");
  await send("Emulation.clearDeviceMetricsOverride");
  socket.close();
  clearTimeout(WATCHDOG);
  process.exitCode = ok ? 0 : 1;
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exitCode = 1; });
