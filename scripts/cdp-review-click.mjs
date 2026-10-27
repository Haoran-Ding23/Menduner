/**
 * 验证「字段行 ✓/✗」真的可用：
 * 1) 打开 /evidence → 行内按钮应为禁用（匿名）；
 * 2) 用演示账号登录（同源 fetch，写会话 Cookie）→ 刷新；
 * 3) 行内按钮应变为可点，点第一个 ✓，读取页面提示。
 *
 * node scripts/cdp-review-click.mjs https://entgroup14.com
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WATCHDOG = setTimeout(() => { console.error("看门狗超时"); process.exit(2); }, 180000);

const PROBE = `(function () {
  const rows = [...document.querySelectorAll('button[aria-label="通过该字段"]')];
  const quick = [...document.querySelectorAll('.quick-btn.ok')];
  return {
    rowButtons: rows.length,
    rowEnabled: rows.filter((b) => !b.disabled).length,
    quickButtons: quick.length,
    quickEnabled: quick.filter((b) => !b.disabled).length,
    whoami: document.body.innerText.includes('登录')
  };
})()`;

async function main() {
  const list = await (await fetch(`${DEBUG}/json/list`)).json();
  const page = list.filter((p) => p.type === "page")[0];
  if (!page) throw new Error("没有页面目标");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  await new Promise((res, rej) => {
    ws.addEventListener("open", res);
    ws.addEventListener("error", () => rej(new Error("WS 失败")));
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
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return result.result ? result.result.value : null;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });

  await send("Page.navigate", { url: BASE + "/evidence" });
  await sleep(9000);
  const before = await evaluate(PROBE);
  console.log("  登录前:", JSON.stringify(before));

  const login = await evaluate(`fetch('/api/account/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ login: 'manager01', password: 'Menduner#2026' })
  }).then(r => r.status)`);
  console.log("  登录状态码:", login);

  const me = await evaluate("fetch('/api/auth/me',{credentials:'include'}).then(r=>r.text())");
  console.log("  /api/auth/me:", me);

  await send("Page.navigate", { url: BASE + "/evidence" });
  await sleep(9000);
  const after = await evaluate(PROBE);
  console.log("  登录后:", JSON.stringify(after));

  const clicked = await evaluate(`(function () {
    const btn = document.querySelector('button[aria-label="通过该字段"]:not([disabled])');
    if (!btn) return 'no-enabled-button';
    btn.click();
    return 'clicked';
  })()`);
  await sleep(4000);
  const message = await evaluate("(document.querySelector('.quick-msg')||{}).innerText || null");
  console.log("  点击结果:", clicked, "| 页面提示:", JSON.stringify(message));

  const ok = (after.rowEnabled > 0) && (before.rowEnabled === 0) && clicked === "clicked";
  console.log(ok ? "[PASS] 行内 ✓ 在登录后可用，点击已发出" : "[FAIL] 行内按钮仍不可用");
  ws.close();
  clearTimeout(WATCHDOG);
  process.exitCode = ok ? 0 : 1;
}

main().catch((e) => { clearTimeout(WATCHDOG); console.error("失败:", e.message); process.exit(1); });
