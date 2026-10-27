/**
 * 按钮可用性审计（精简快速版 v2）。
 *
 * 与 v1 的差别：
 *  - 只测可见、未禁用的控件，每页最多 CAP 个（默认 18），先保证能跑完、能出结果；
 *  - 页内点击发生跳转时立即回到该页，但只回一次（避免无限循环）；
 *  - 每点一个控件都打印一行，便于实时观察进度；
 *  - 结果写 JSON，便于后续按清单修。
 *
 * node scripts/cdp-button-audit-v2.mjs [base] [--pages /map,/graph] [--json out.json] [--cap 18]
 */
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const BASE = argv[0] && !argv[0].startsWith("--") ? argv[0] : "https://entgroup14.com";
const JSON_OUT = getArg("--json", "deliverables/button-audit.json");
const CAP = Number(getArg("--cap", "18"));
const ONLY = getArg("--pages", "");
// 审计只验证"有没有反应"，绝不允许写入真实数据：
// 生成/保存/审核/删除/导入这类动作在审计中一律跳过，改为在专门的测试里验证。
const DESTRUCTIVE = /(生成|保存|提交|确认|审核|核查完毕|删除|导入|撤回|补录|对$|错$|通过|驳回|清空|重置数据)/;

const DEBUG = "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ALL_PAGES = [
  ["/workbench", "工作台"],
  ["/map", "地图"],
  ["/agenda", "活动清单"],
  ["/hotels", "找酒店"],
  ["/hotel-activity", "酒店活动情报"],
  ["/insights", "商圈洞察"],
  ["/graph", "知识图谱"],
  ["/evidence", "数据质量"],
  ["/review", "审核台"],
  ["/more", "更多"],
];
const PAGES = ONLY
  ? ALL_PAGES.filter(([p]) => ONLY.split(",").includes(p))
  : ALL_PAGES;

const INSTRUMENT = `(function(){
  if (window.__audit) { window.__audit.mutations = 0; window.__audit.fetches = 0; return 'reset'; }
  window.__audit = { mutations: 0, fetches: 0 };
  new MutationObserver((l) => { window.__audit.mutations += l.length; })
    .observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  const of = window.fetch;
  window.fetch = function(...a) { window.__audit.fetches += 1; return of.apply(this, a); };
  const oo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(...a) { window.__audit.fetches += 1; return oo.apply(this, a); };
  return 'ok';
})()`;

const COLLECT = `(function(){
  const out = [];
  const seen = new Set();
  document.querySelectorAll('button, .ant-switch, [role="switch"], a[href], .ant-segmented-item, [role="tab"]')
    .forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) return;
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') return;
      // 侧边导航单独看（它们都是跳转，不是页面功能），避免把审计时间耗在导航上
      if (el.closest('aside, nav, .sidebar, [class*="sider"], [class*="layout-menu"]')) return;
      const label = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 26);
      // 破坏性操作一律跳过（正则必须写字面量：这段代码在浏览器里执行）
      if (/生成|保存|提交|确认|审核|核查完毕|删除|导入|撤回|补录|^对$|^错$|通过|驳回|清空|重置数据/.test(label)) return;
      const key = el.tagName + '|' + label + '|' + Math.round(r.x) + ',' + Math.round(r.y);
      if (seen.has(key)) return;
      seen.add(key);
      el.setAttribute('data-audit-idx', String(out.length));
      out.push({ index: out.length, tag: el.tagName.toLowerCase(), label: label || '(无文字)' });
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
      const timer = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 25000);
      pending.set(mid, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return result.result ? result.result.value : null;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  const report = [];
  for (const [path, name] of PAGES) {
    await send("Page.navigate", { url: BASE + path });
    await sleep(13000);
    await evaluate(INSTRUMENT);
    const controls = (await evaluate(COLLECT)) || [];
    const rows = [];
    for (const control of controls.slice(0, CAP)) {
      const clicked = await evaluate(`(function(){
        const el = document.querySelector('[data-audit-idx="${control.index}"]');
        if (!el) return 'missing';
        el.click(); return 'ok';})()`);
      await sleep(1300);
      const after = await evaluate(`({ href: location.pathname + location.search,
        mutations: window.__audit.mutations, fetches: window.__audit.fetches,
        overlay: document.querySelectorAll('.ant-modal, .ant-drawer-open, .ant-message').length })`);
      if (!after) {
        // 点击导致页面开始跳转：这本身是有作用的（navigate），不是 NO-OP。
        rows.push({ ...control, verdict: 'navigate', mutations: -1, fetches: -1 });
        console.log('      · [' + control.tag + '] ' + control.label + ' → navigate(跳转中)');
        await send('Page.navigate', { url: BASE + path });
        await sleep(12000);
        await evaluate(INSTRUMENT);
        await evaluate(COLLECT);
        continue;
      }
      const navigated = after.href !== path;
      let verdict = "NO-OP";
      if (clicked === "missing") verdict = "missing";
      else if (navigated) verdict = "navigate";
      else if (after.fetches > 0 || after.mutations >= 6 || after.overlay > 0) verdict = "effect";
      rows.push({ ...control, verdict, mutations: after.mutations, fetches: after.fetches });
      console.log(`      ${verdict === "NO-OP" ? "✗" : "·"} [${control.tag}] ${control.label} → ${verdict}`);
      if (navigated) {
        await send("Page.navigate", { url: BASE + path });
        await sleep(12000);
        await evaluate(INSTRUMENT);
        await evaluate(COLLECT);
      }
    }
    const summary = {
      page: path,
      name,
      controls: controls.length,
      tested: rows.length,
      noop: rows.filter((r) => r.verdict === "NO-OP").length,
      rows,
    };
    report.push(summary);
    console.log(`  === ${name} (${path}) 控件 ${summary.controls} · 测 ${summary.tested} · 无反应 ${summary.noop}`);
  }

  writeFileSync(JSON_OUT, JSON.stringify(report, null, 2));
  const total = report.reduce((s, p) => s + p.noop, 0);
  console.log(`\n  合计 NO-OP: ${total}（明细 ${JSON_OUT}）`);
  ws.close();
  process.exitCode = 0;
}

main().catch((error) => { console.error("失败:", error.message); process.exit(1); });
