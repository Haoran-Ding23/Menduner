/**
 * 控件可用性审计（Playwright 版）—— 取代裸 CDP 脚本。
 *
 * 为什么换：裸 CDP 脚本在审核台页面反复卡死（Page.enable / Runtime.evaluate 超时），
 * 而且我自己在"破坏性跳过"上连续写错三次。Playwright 自带自动等待与稳定选择器，
 * 更适合做这种"逐控件点击 + 判定效果"的回归检查。
 *
 * 判定口径（与 docs/CONTROL_ACCEPTANCE_LEDGER.md 一致）：
 *   disabled → 控件禁用（需人工确认是否有解释）
 *   navigate → URL 变化
 *   effect   → DOM 变化 ≥6 或触发请求或出现弹窗
 *   NO-OP    → 以上都没有（必须修）
 *
 * 安全：写入类控件（生成/保存/提交/审核/通过/驳回/修正/补录/对/错/删除/导入/撤回/清空）一律跳过，
 *       审计只验证"有没有反应"，绝不改生产数据。
 *
 * 用法（在 frontend 目录下运行）：
 *   node scripts/pw-audit.mjs                    # 默认全部页面 + 登录态
 *   node scripts/pw-audit.mjs --pages /review    # 只测某页
 *   node scripts/pw-audit.mjs --no-auth          # 不登录（看匿名态）
 *   node scripts/pw-audit.mjs --json out.json --cap 120
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const BASE = getArg("--base", "https://entgroup14.com");
const CAP = Number(getArg("--cap", "150"));
const JSON_OUT = getArg("--json", "../deliverables/pw-audit.json");
const ONLY = getArg("--pages", "");
const AUTH = !argv.includes("--no-auth");
const LOGIN = getArg("--login", "menduner");
const PASSWORD = getArg("--password", "123456");

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
].filter(([path]) => (ONLY ? ONLY.split(",").includes(path) : true));

/** 写入类控件：不点。先把空白去掉再判断（按钮文案可能是「通 过」）。 */
const DESTRUCTIVE =
  /生成|保存|提交|确认|审核|核查完毕|删除|导入|撤回|补录|^对$|^错$|通过|驳回|修正|清空|重置数据|开通|取消/;

const INSTRUMENT = () => {
  window.__audit = window.__audit || { mutations: 0, fetches: 0 };
  window.__audit.mutations = 0;
  window.__audit.fetches = 0;
  if (!window.__auditObserver) {
    window.__auditObserver = new MutationObserver((list) => {
      window.__audit.mutations += list.length;
    });
    window.__auditObserver.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
      window.__audit.fetches += 1;
      return originalFetch.apply(this, args);
    };
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (...args) {
      window.__audit.fetches += 1;
      return originalOpen.apply(this, args);
    };
  }
};

const COLLECT = () => {
  const out = [];
  const seen = new Set();
  document
    .querySelectorAll('button, .ant-switch, [role="switch"], .ant-segmented-item, [role="tab"]')
    .forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width < 6 || rect.height < 6) return;
      if (el.disabled || el.getAttribute("aria-disabled") === "true") return;
      if (el.closest('aside, nav, .sidebar, [class*="sider"], [class*="layout-menu"]')) return;
      const label = (el.getAttribute("aria-label") || el.textContent || "")
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 30);
      const key = el.tagName + "|" + label + "|" + Math.round(rect.x) + "," + Math.round(rect.y);
      if (seen.has(key)) return;
      seen.add(key);
      el.setAttribute("data-pw-audit", String(out.length));
      out.push({ index: out.length, tag: el.tagName.toLowerCase(), label: label || "(无文字)" });
    });
  return out;
};

async function main() {
  // 优先用系统已安装的 Chrome（channel: 'chrome'），免得再下载一套 Chromium
  const browser = await chromium
    .launch({ headless: true, channel: 'chrome' })
    .catch(async () => chromium.launch({ headless: true }));
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);

  if (AUTH) {
    const response = await context.request.post(BASE + "/api/account/login", {
      data: { login: LOGIN, password: PASSWORD },
    });
    console.log("  登录状态:", response.status());
  }

  const report = [];
  for (const [path, name] of PAGES) {
    await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(9000);
    await page.evaluate(INSTRUMENT);

    let controls = await page.evaluate(COLLECT);
    const rows = [];
    for (const control of controls.slice(0, CAP)) {
      const compact = control.label.replace(/\s+/g, "");
      if (DESTRUCTIVE.test(compact)) {
        rows.push({ ...control, verdict: "skipped-destructive" });
        continue;
      }
      const beforeUrl = page.url();
      const clicked = await page
        .locator(`[data-pw-audit="${control.index}"]`)
        .first()
        .click({ timeout: 5000, noWaitAfter: true })
        .then(() => "ok")
        .catch(() => "failed");
      await page.waitForTimeout(900);
      let after = null;
      try {
        after = await page.evaluate(() => ({
          url: location.pathname + location.search,
          mutations: window.__audit.mutations,
          fetches: window.__audit.fetches,
          overlays: document.querySelectorAll(".ant-modal, .ant-drawer-open, .ant-message").length,
        }));
      } catch {
        after = null;
      }
      let verdict = "NO-OP";
      if (clicked !== "ok") verdict = "click-failed";
      else if (!after) verdict = "navigate";
      else if (after.url !== new URL(beforeUrl).pathname + new URL(beforeUrl).search) verdict = "navigate";
      else if (after.fetches > 0 || after.mutations >= 6 || after.overlays > 0) verdict = "effect";

      rows.push({ ...control, verdict, mutations: after?.mutations ?? -1, fetches: after?.fetches ?? -1 });
      console.log(`      ${verdict === "NO-OP" ? "✗" : "·"} [${control.tag}] ${control.label} → ${verdict}`);

      if (verdict === "navigate") {
        await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(8000);
        await page.evaluate(INSTRUMENT);
        controls = await page.evaluate(COLLECT);
      }
    }

    const noop = rows.filter((r) => r.verdict === "NO-OP").length;
    report.push({ page: path, name, controls: controls.length, tested: rows.length, noop, rows });
    console.log(`  === ${name} (${path}) 控件 ${controls.length} · 测 ${rows.length} · 无反应 ${noop}`);
  }

  writeFileSync(JSON_OUT, JSON.stringify(report, null, 2));
  const total = report.reduce((sum, item) => sum + item.noop, 0);
  console.log(`\n  合计 NO-OP: ${total}（明细 ${JSON_OUT}）`);
  await browser.close();
  process.exitCode = total === 0 ? 0 : 1;
}

main().catch((error) => {
  console.error("失败:", error.message);
  process.exit(1);
});
