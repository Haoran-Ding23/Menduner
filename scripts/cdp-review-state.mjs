/**
 * 核实审核页当前状态：登录后读取三行快速核对的状态标签与按钮可用性，
 * 并找一条仍有待核对字段的活动，确认按钮在该活动上可点。
 *
 * node scripts/cdp-review-state.mjs https://entgroup14.com
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗超时"); process.exit(2); }, 180000);

const PROBE = `(function () {
  const rows = [...document.querySelectorAll('.quick-row')].map((row) => ({
    label: (row.querySelector('.quick-label')||{}).textContent || '',
    value: ((row.querySelector('.quick-value')||{}).textContent || '').slice(0, 40),
    status: (row.querySelector('.quick-status')||{}).textContent || '',
    ok: !!row.querySelector('button.quick-btn.ok:not([disabled])'),
  }));
  const tableRows = [...document.querySelectorAll('button[aria-label="通过该字段"]')];
  return {
    quick: rows,
    rowButtons: tableRows.length,
    rowEnabled: tableRows.filter((b) => !b.disabled).length,
    total: (document.querySelector('.dq-head')||{}).textContent || ''
  };
})()`;

async function main() {
  const list = await (await fetch(`${DEBUG}/json/list`)).json();
  const page = list.filter((p) => p.type === "page")[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  await new Promise((res, rej) => {
    ws.addEventListener("open", res);
    ws.addEventListener("error", () => rej(new Error("WS 失败")));
  });
  ws.addEventListener("message", async (event) => {
    let raw = typeof event.data === "string" ? event.data : Buffer.from(event.data).toString("utf8");
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
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return result.result ? result.result.value : null;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: BASE + "/evidence" });
  await sleep(8000);

  await evaluate(`fetch('/api/account/login', { method:'POST', headers:{'Content-Type':'application/json'},
    credentials:'include', body: JSON.stringify({ login:'manager01', password:'Menduner#2026' }) }).then(r=>r.status)`);
  await send("Page.navigate", { url: BASE + "/evidence" });
  await sleep(9000);

  const state = await evaluate(PROBE);
  console.log(JSON.stringify(state, null, 2));

  // 再点第一行未被禁用的按钮，确认真的提交并刷新
  const clicked = await evaluate(`(function () {
    const btn = document.querySelector('button.quick-btn.no:not([disabled])');
    if (!btn) return 'none';
    btn.click();
    return 'clicked-reject';
  })()`);
  await sleep(5000);
  const after = await evaluate(PROBE);
  console.log("点击:", clicked, "| 点击后第一行状态:", after && after.quick && after.quick[0] ? after.quick[0].status : null);
  ws.close();
  clearTimeout(WATCHDOG);
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exit(1); });
