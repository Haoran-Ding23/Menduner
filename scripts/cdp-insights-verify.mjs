/**
 * 商圈洞察页真实渲染检查（口径变更后同步更新断言）。
 * 关注：三块内容是否渲染、是否出现「官方商圈 / 候选集聚点」区分、三档对照与供给画像是否在位。
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = process.argv[3] ?? "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗超时"); process.exit(2); }, 120000);

const PROBE = [
  '(function () {',
  '  var text = document.body.innerText || "";',
  '  var stat = document.querySelectorAll(".stat-row strong");',
  '  var values = Array.prototype.slice.call(stat).map(function (el) { return el.textContent.trim(); });',
  '  return {',
  '    hasCoverage: text.indexOf("商圈数据能力") >= 0,',
  '    hasProfile: text.indexOf("单商圈画像") >= 0,',
  '    hasAdmin: text.indexOf("原始归属") >= 0,',
  '    hasRadiusLabel: text.indexOf("近邻分析范围") >= 0,',
  '    hasOfficial: text.indexOf("官方商圈") >= 0,',
  '    hasCandidate: text.indexOf("候选集聚点") >= 0,',
  '    hasSupply: text.indexOf("供给画像") >= 0,',
  '    statValues: values.slice(0, 14),',
  '    bars: document.querySelectorAll(".bar-row").length,',
  '    compares: document.querySelectorAll(".compare-table tbody tr").length,',
  '    len: text.length',
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
      pending.set(mid, { resolve: (v) => { clearTimeout(t); resolve(v); }, reject: (e) => { clearTimeout(t); reject(e); } });
      socket.send(JSON.stringify({ id: mid, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: BASE + "/insights" });

  let value = null;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await sleep(2500);
    const result = await send("Runtime.evaluate", { expression: PROBE, returnByValue: true });
    value = result.result ? result.result.value : null;
    if (value && value.statValues && value.statValues.length >= 6 && value.hasSupply) break;
  }
  console.log("  渲染检查:", JSON.stringify(value));
  const ok = value && value.hasCoverage && value.hasProfile && value.hasAdmin
    && value.hasRadiusLabel && value.hasOfficial && value.hasSupply
    && value.statValues.length >= 6 && value.compares === 3;
  console.log(ok ? "[PASS] 三块内容 + 官方/候选区分 + 三档对照 + 供给画像均渲染" : "[FAIL] 见上");
  await send("Emulation.clearDeviceMetricsOverride");
  socket.close();
  clearTimeout(WATCHDOG);
  process.exitCode = ok ? 0 : 1;
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exitCode = 1; });
