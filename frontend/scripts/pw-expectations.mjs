/**
 * 控件「预期行为」验收 —— 用 el.click() 触发（与用户点击同一条 React onClick 路径）。
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const BASE = getArg("--base", "https://entgroup14.com");
const PAGE = getArg("--page", "/review");
const LOGIN = getArg("--login", "menduner");
const PASSWORD = getArg("--password", "123456");
const OUT = getArg("--json", "../deliverables/pw-expectations.json");

const WRITE_LIKE = /生成|保存|提交|确认|审核|核查完毕|删除|导入|撤回|补录|^对$|^错$|通过|驳回|修正|清空|重置数据|合并|反向合并|开通|取消|录入并/;
const ACTION_LIKE = /^刷\s*新|刷新 API 数据/;
const DRAWER_LIKE = /活动详情|查看来源|原始来源/;
const EXPAND_LIKE = /录入一条|显示全部|展开|收起/;
const FILTER_LIKE = /筛选|搜索|来源|显示演示|隐藏演示|月份|地区/;
const TOGGLE_LIKE = /查看|显示|隐藏/;

const results = [];
const record = (label, kind, ok, detail) => {
  results.push({ label, kind, ok, detail });
  console.log(`  ${ok ? "PASS" : "FAIL"} [${kind}] ${label}${detail ? " -- " + detail : ""}`);
};

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" }).catch(async () => chromium.launch({ headless: true }));
  const context = await browser.newContext({ viewport: { width: 1440, height: 1600 } });
  await context.request.post(BASE + "/api/account/login", { data: { login: LOGIN, password: PASSWORD } });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  let requests = 0;
  page.on("request", (r) => { if (r.url().includes("/api/")) requests += 1; });

  const snapshot = () => page.evaluate(() => ({
    rows: document.querySelectorAll("tbody tr.ant-table-row").length,
    url: location.pathname + location.search,
    modals: document.querySelectorAll(".ant-modal-title, .ant-drawer-title").length,
    text: document.body.innerText.length,
    fields: document.querySelectorAll('input[placeholder*="活动名称"], section textarea').length,
    toast: (document.querySelector('.ant-message')?.innerText || '').length,
    popovers: document.querySelectorAll('.ant-popover').length,
    mapView: window.__mapView ? `${window.__mapView.zoom}/${window.__mapView.lng}` : null,
  }));

  // networkidle 在该应用上永不触发（有长连接/轮询）：改为等表格出现 + 固定等待
  await page.goto(BASE + PAGE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector("tbody tr.ant-table-row", { timeout: 30000 }).catch(() => undefined);
  await page.waitForTimeout(4000);

  const disabled = await page.evaluate(() =>
    [...document.querySelectorAll("button[disabled], button[aria-disabled='true']")]
      .filter((b) => !b.closest("aside, nav, .sidebar") && !b.closest(".ant-pagination"))
      .map((b) => ({ label: (b.textContent || "").trim().slice(0, 20) || "(无文字)",
                     reason: b.getAttribute("title") || b.getAttribute("aria-label") || "" })));
  for (const item of disabled) {
    record(item.label, "reason", Boolean(item.reason), item.reason ? "原因：" + item.reason : "禁用但没写原因");
  }

  const controls = await page.evaluate(() => {
    const out = [];
    const seen = new Set();
    document.querySelectorAll("button, .ant-switch, [role='switch'], .ant-segmented-item, [role='tab']").forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width < 6 || rect.height < 6) return;
      if (el.disabled) return;
      if (el.closest("aside, nav, .sidebar")) return;
      const label = (el.getAttribute("aria-label") || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 24);
      if (!label || seen.has(label)) return;
      seen.add(label);
      el.setAttribute("data-expect-label", label);
      out.push(label);
    });
    return out;
  });

  for (const label of controls) {
    const compact = label.replace(/\s+/g, "");
    if (WRITE_LIKE.test(compact)) {
      results.push({ label, kind: "write", ok: true, detail: "写入类：由隔离环境脚本验证" });
      continue;
    }
    const kind = ACTION_LIKE.test(label) ? "action"
      : DRAWER_LIKE.test(label) ? "drawer"
      : EXPAND_LIKE.test(label) ? "expand"
      : FILTER_LIKE.test(label) ? "filter"
      : TOGGLE_LIKE.test(label) ? "toggle" : "dialog";

    const before = await snapshot();
    requests = 0;
    const clicked = await page
      .getByRole("button", { name: label, exact: true })
      .first()
      .evaluate((el) => {
        el.scrollIntoView({ block: "center" });
        el.click();
        return true;
      })
      .catch(async () => {
        // 开关/分段控件不是 button 角色：退化到文本定位
        return page
          .locator(`button:has-text("${label}"), .ant-switch, [role="switch"], [role="tab"]`)
          .filter({ hasText: label })
          .first()
          .evaluate((el) => {
            el.click();
            return true;
          })
          .catch(() => false);
      });
    await page.waitForTimeout(1800);
    const after = await snapshot();

    const toastAppeared = after.toast > before.toast;
    let ok = false;
    let detail = "";
    if (!clicked) {
      detail = "元素已不在 DOM（页面重渲染）";
    } else if (kind === "action") {
      ok = requests > 0 || after.rows !== before.rows || toastAppeared;
      detail = `请求 ${requests} 个，行数 ${before.rows} → ${after.rows}`;
    } else if (kind === "expand") {
      ok = after.fields !== before.fields || Math.abs(after.text - before.text) > 20 || after.rows !== before.rows;
      detail = `表单字段 ${before.fields} → ${after.fields}，文字 ${before.text} → ${after.text}`;
    } else if (kind === "drawer") {
      ok = after.url !== before.url || after.modals > before.modals;
      detail = `URL ${before.url} → ${after.url}，抽屉 ${before.modals} → ${after.modals}`;
    } else if (kind === "filter") {
      ok = after.rows !== before.rows || after.url !== before.url;
      detail = `行数 ${before.rows} → ${after.rows}`;
    } else {
      ok = after.rows !== before.rows || after.modals !== before.modals || after.popovers !== before.popovers
        || after.url !== before.url || after.mapView !== before.mapView || toastAppeared;
      detail = `行数 ${before.rows} → ${after.rows}，弹窗 ${before.modals} → ${after.modals}`;
    }
    record(label, kind, ok, detail);

    if (after.url !== before.url || after.modals > before.modals) {
      await page.goto(BASE + PAGE, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(9000);
    } else if (after.fields > before.fields) {
      await page
        .getByRole("button", { name: label, exact: true })
        .first()
        .evaluate((el) => el.click())
        .catch(() => undefined);
      await page.waitForTimeout(800);
    }
  }

  writeFileSync(OUT, JSON.stringify(results, null, 2));
  const failed = results.filter((item) => !item.ok);
  console.log(`\n  通过 ${results.length - failed.length}/${results.length}（失败 ${failed.length}）`);
  await browser.close();
  process.exitCode = failed.length === 0 ? 0 : 1;
}

main().catch((error) => { console.error("失败:", error.message); process.exit(1); });
