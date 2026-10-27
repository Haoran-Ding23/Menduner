/**
 * 按钮可用性审计：逐页枚举所有可交互控件，点击后判断「有没有产生效果」。
 *
 * 判定口径（写死，避免主观）：
 *   disabled  → 控件被禁用（记录为 disabled，需要看是否需要角色）
 *   navigate  → 点击后 URL 变化（视为有作用）
 *   effect    → DOM 变化 ≥ 6 次 或 触发网络请求 或 出现 toast/弹窗（视为有作用）
 *   NO-OP     → 点击后以上都没有（这是要修的真问题）
 *
 * 用法：
 *   node scripts/cdp-button-audit.mjs [base] [--json 输出文件]
 */
import { writeFileSync } from "node:fs";

const BASE = process.argv[2] && !process.argv[2].startsWith("--") ? process.argv[2] : "https://entgroup14.com";
const JSON_OUT = process.argv.includes("--json") ? process.argv[process.argv.indexOf("--json") + 1] : null;
const DEBUG = "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PAGES = [
  ["/workbench", "本店工作台"],
  ["/map", "城市活动地图"],
  ["/agenda", "活动清单"],
  ["/hotels", "找酒店"],
  ["/hotel-activity", "酒店活动情报"],
  ["/insights", "商圈洞察"],
  ["/graph", "知识图谱"],
  ["/evidence", "数据质量与来源"],
  ["/review", "审核台"],
  ["/more", "更多"],
];

const INSTRUMENT = `(function(){
  if (window.__audit) return 'already';
  window.__audit = { mutations: 0, fetches: 0 };
  const obs = new MutationObserver((list) => { window.__audit.mutations += list.length; });
  obs.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  const originalFetch = window.fetch;
  window.fetch = function(...args) { window.__audit.fetches += 1; return originalFetch.apply(this, args); };
  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(...args) { window.__audit.fetches += 1; return originalOpen.apply(this, args); };
  return 'ok';
})()`;

const COLLECT = `(function(){
  const seen = new Set();
  const out = [];
  const nodes = document.querySelectorAll('button, [role="switch"], .ant-switch, a[href], [role="tab"], .ant-segmented-item');
  nodes.forEach((el, index) => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return;
    const label = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 28);
    const key = (el.tagName + '|' + label + '|' + Math.round(rect.x) + ',' + Math.round(rect.y));
    if (seen.has(key)) return;
    seen.add(key);
    el.setAttribute('data-audit-index', String(out.length));
    out.push({
      index: out.length,
      tag: el.tagName.toLowerCase(),
      label: label || ('(无文字 ' + el.tagName.toLowerCase() + ')'),
      disabled: Boolean(el.disabled) || el.getAttribute('aria-disabled') === 'true',
      href: el.getAttribute('href') || null
    });
  });
  return out;
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
    const raw = typeof event.data === "string" ? event.data : Buffer.from(event.data).toString("utf8");
    const msg = JSON.parse(raw);
    const entry = msg.id ? pending.get(msg.id) : null;
    if (!entry) return;
    pending.delete(msg.id);
    msg.error ? entry.reject(new Error(msg.error.message)) : entry.resolve(msg.result);
  });
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const mid = ++id;
      const timer = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 40000);
      pending.set(mid, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) return { __error: result.exceptionDetails.text };
    return result.result ? result.result.value : null;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.clearBrowserCookies").catch(() => undefined);
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  const findings = [];
  for (const [path, name] of PAGES) {
    await send("Page.navigate", { url: BASE + path });
    await sleep(15000);
    await evaluate(INSTRUMENT);
    const controls = (await evaluate(COLLECT)) || [];
    const usable = controls.filter((c) => !c.disabled);
    const rows = [];
    for (const control of usable.slice(0, 45)) {
      const before = await evaluate(`(function(){
        window.__audit.mutations = 0; window.__audit.fetches = 0;
        return { href: location.pathname + location.search,
                 overlays: document.querySelectorAll('.ant-modal, .ant-drawer-open, .ant-message').length,
                 scrollY: window.scrollY };
      })()`);
      const clicked = await evaluate(`(function(){
        const el = document.querySelector('[data-audit-index="${control.index}"]');
        if (!el) return 'missing';
        el.click();
        return 'ok';
      })()`);
      await sleep(1400);
      const after = await evaluate(`(function(){
        return { href: location.pathname + location.search,
                 mutations: window.__audit.mutations,
                 fetches: window.__audit.fetches,
                 overlays: document.querySelectorAll('.ant-modal, .ant-drawer-open, .ant-message').length };
      })()`);
      let verdict = "NO-OP";
      if (clicked === "missing") verdict = "missing";
      else if (after.href !== before.href) verdict = "navigate";
      else if (after.fetches > 0 || after.mutations >= 6 || after.overlays > before.overlays) verdict = "effect";
      rows.push({ ...control, verdict, mutations: after.mutations, fetches: after.fetches });
      if (after.href !== before.href) {
        // 发生了跳转：回到本页继续测
        await send("Page.navigate", { url: BASE + path });
        await sleep(12000);
        await evaluate(INSTRUMENT);
        await evaluate(COLLECT);
      }
    }

    const summary = {
      page: path,
      name,
      total: controls.length,
      disabled: controls.length - usable.length,
      tested: rows.length,
      noop: rows.filter((r) => r.verdict === "NO-OP").length,
      rows,
    };
    findings.push(summary);
    console.log(
      `  ${name.padEnd(8)} 控件 ${String(summary.total).padStart(3)} · 禁用 ${String(summary.disabled).padStart(2)} · 测得 ${String(summary.tested).padStart(2)} · 无反应 ${summary.noop}`,
    );
    rows
      .filter((r) => r.verdict === "NO-OP")
      .forEach((r) => console.log(`      ✗ [${r.tag}] ${r.label}`));
  }

  const totalNoop = findings.reduce((sum, item) => sum + item.noop, 0);
  console.log(`\n  合计无反应控件：${totalNoop}`);
  if (JSON_OUT) {
    writeFileSync(JSON_OUT, JSON.stringify(findings, null, 2));
    console.log(`  明细已写入 ${JSON_OUT}`);
  }
  ws.close();
  process.exitCode = totalNoop === 0 ? 0 : 1;
}

main().catch((error) => { console.error("失败:", error.message); process.exit(1); });
