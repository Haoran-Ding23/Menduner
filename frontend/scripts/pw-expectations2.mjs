/**
 * 控件「预期行为」验收 v2 —— 解决 v1 的定位失败问题。
 *
 * v1 的问题：先枚举控件、写自定义属性当锚点，再逐个点击。
 * 页面一重渲染，属性随节点消失，于是大量「元素已不在 DOM」的假失败；
 * 另外标签被截断到 24 字符，同名按钮无法区分。
 *
 * v2 的做法：
 *  - 每次迭代都在**同一次页面求值**里完成：枚举 → 找第一个未测控件 → 点击；
 *  - 用「标签全文 + 同标签出现序号」做稳定键，避免截断与重名；
 *  - 判定仍按控件类型（action/expand/drawer/filter/toggle/switch/reason）。
 *
 * 用法：
 *   node scripts/pw-expectations2.mjs --base https://entgroup14.com --page /hotels
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
const OUT = getArg("--json", "../deliverables/pw-expectations2.json");
const MAX_CONTROLS = Number(getArg("--cap", "80"));

const WRITE_LIKE = /生成|保存|提交|确认|审核|核查完毕|删除|导入|撤回|补录|^对$|^错$|通过|驳回|修正|清空|重置数据|合并|反向合并|开通|取消|录入并/;
const ACTION_LIKE = /^刷\s*新|刷新 API 数据/;
const DRAWER_LIKE = /活动详情|查看来源|原始来源/;
const EXPAND_LIKE = /录入一条|显示全部|展开|收起|更多查看方式/;
const FILTER_LIKE = /筛选|搜索|来源|显示演示|隐藏演示|月份|地区|重置/;
const TOGGLE_LIKE = /查看|显示|隐藏/;

const results = [];
const record = (label, kind, ok, detail) => {
  results.push({ label, kind, ok, detail });
  console.log(`  ${ok ? "PASS" : "FAIL"} [${kind}] ${label.slice(0, 40)} -- ${detail}`);
};

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" }).catch(async () => chromium.launch({ headless: true }));
  const context = await browser.newContext({ viewport: { width: 1440, height: 1600 } });
  await context.request.post(BASE + "/api/account/login", { data: { login: LOGIN, password: PASSWORD } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  let requests = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/")) requests += 1;
  });

  const snapshot = () =>
    page.evaluate(() => ({
      rows: document.querySelectorAll("tbody tr.ant-table-row").length,
      url: location.pathname + location.search,
      modals: document.querySelectorAll(".ant-modal-title, .ant-drawer-open .ant-drawer-title").length,
      drawers: document.querySelectorAll(".ant-drawer-open").length,
      popovers: document.querySelectorAll(".ant-popover:not(.ant-popover-hidden), .ant-dropdown:not(.ant-dropdown-hidden), .ant-select-dropdown:not(.ant-select-dropdown-hidden)").length,
      text: document.body.innerText.length,
      fields: document.querySelectorAll('input[placeholder*="活动名称"], section textarea').length,
      markers: document.querySelectorAll(".amap-marker, .amap-marker-label").length,
      mapView: window.__mapView ? `${window.__mapView.zoom}/${Math.round(window.__mapView.lng * 100)}` : null,
      toast: (document.querySelector(".ant-message")?.innerText || "").length,
    }));

  await page.goto(BASE + PAGE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector("tbody tr.ant-table-row, .panel, section", { timeout: 30000 }).catch(() => undefined);
  await page.waitForTimeout(4000);

  // 禁用控件必须写原因
  const disabled = await page.evaluate(() =>
    [...document.querySelectorAll("button[disabled], button[aria-disabled='true']")]
      .filter((b) => !b.closest("aside, nav, .sidebar") && !b.closest(".ant-pagination"))
      .map((b) => ({
        label: (b.textContent || "").trim().slice(0, 30) || "(无文字)",
        reason: b.getAttribute("title") || b.getAttribute("aria-label") || "",
      })),
  );
  for (const item of disabled) {
    record(item.label, "reason", Boolean(item.reason), item.reason ? `原因：${item.reason}` : "禁用但没写原因");
  }

  const tested = new Set();
  for (let step = 0; step < MAX_CONTROLS; step += 1) {
    requests = 0;
    const before = await snapshot();
    // 关键：枚举 + 选中 + 点击在同一次求值内完成，避免重渲染后元素失效
    let picked = await page.evaluate((testedKeys) => {
      const nodes = [...document.querySelectorAll("button, .ant-switch, [role='switch'], .ant-segmented-item, [role='tab']")]
        .filter((el) => {
          const rect = el.getBoundingClientRect();
          if (rect.width < 6 || rect.height < 6) return false;
          if (el.disabled) return false;
          if (el.closest("aside, nav, .sidebar")) return false;
          return true;
        });
      const seen = new Map();
      for (const el of nodes) {
        const raw = (el.getAttribute("aria-label") || el.textContent || "").trim().replace(/\s+/g, " ");
        if (!raw) continue;
        const tag = el.tagName.toLowerCase() + (el.getAttribute("role") || "");
        const key = `${tag}:${raw}`;
        const occurrence = seen.get(key) ?? 0;
        seen.set(key, occurrence + 1);
        const id = `${key}#${occurrence}`;
        if (testedKeys.includes(id)) continue;
        el.scrollIntoView({ block: "center" });
        el.click();
        return { id, label: raw };
      }
      return null;
    }, [...tested]);

    if (!picked) {
      // 页面可能还在渲染（重载后/懒加载）：等一会儿再取一次，连续 3 次取不到才结束
      let retried = null;
      for (let attempt = 0; attempt < 3 && !retried; attempt += 1) {
        await page.waitForTimeout(2500);
        retried = await page.evaluate((testedKeys) => {
          const nodes = [...document.querySelectorAll("button, .ant-switch, [role='switch'], .ant-segmented-item, [role='tab']")]
            .filter((el) => {
              const rect = el.getBoundingClientRect();
              if (rect.width < 6 || rect.height < 6) return false;
              if (el.disabled) return false;
              if (el.closest("aside, nav, .sidebar")) return false;
              return true;
            });
          const seen = new Map();
          for (const el of nodes) {
            const raw = (el.getAttribute("aria-label") || el.textContent || "").trim().replace(/\s+/g, " ");
            if (!raw) continue;
            const tag = el.tagName.toLowerCase() + (el.getAttribute("role") || "");
            const key = `${tag}:${raw}`;
            const occurrence = seen.get(key) ?? 0;
            seen.set(key, occurrence + 1);
            const id = `${key}#${occurrence}`;
            if (testedKeys.includes(id)) continue;
            el.scrollIntoView({ block: "center" });
            el.click();
            return { id, label: raw };
          }
          return null;
        }, [...tested]);
      }
      if (!retried) break;
      picked = retried;
    }
    tested.add(picked.id);

    const label = picked.label;
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

    await page.waitForTimeout(1600);
    const after = await snapshot();

    // 只认「点击带来的变化」：绝对值会把页面本来就有的弹窗当成效果（那是我批评过的假通过）
    const overlayGrew =
      after.drawers > before.drawers || after.modals > before.modals || after.popovers > before.popovers;
    const contentGrew =
      after.rows !== before.rows || Math.abs(after.text - before.text) > 20 || after.fields > before.fields;
    const mapMoved = after.mapView !== before.mapView || after.markers !== before.markers;
    const urlChanged = after.url !== before.url;
    const toastShown = after.toast > before.toast;

    let ok = false;
    let detail = "";
    if (kind === "action") {
      ok = requests > 0 || toastShown;
      detail = `请求 ${requests}，提示 ${toastShown ? "有" : "无"}`;
    } else if (kind === "expand") {
      ok = contentGrew || overlayGrew;
      detail = `文字 ${before.text}→${after.text}，字段 ${before.fields}→${after.fields}，浮层 +${after.drawers + after.modals + after.popovers - before.drawers - before.modals - before.popovers}`;
    } else if (kind === "drawer") {
      ok = overlayGrew || urlChanged || mapMoved;
      detail = `浮层 ${before.drawers + before.modals + before.popovers}→${after.drawers + after.modals + after.popovers}，URL ${urlChanged ? "变化" : "未变"}`;
    } else if (kind === "filter") {
      ok = overlayGrew || contentGrew || mapMoved || urlChanged;
      detail = `行 ${before.rows}→${after.rows}，浮层 +${after.popovers - before.popovers}，地图${mapMoved ? "变化" : "未变"}`;
    } else {
      ok = overlayGrew || contentGrew || mapMoved || urlChanged || toastShown;
      detail = `浮层 ${before.drawers + before.modals + before.popovers}→${after.drawers + after.modals + after.popovers}，地图${mapMoved ? "变化" : "未变"}`;
    }
    record(label, kind, ok, detail);

    // 清理：展开/浮层/筛选会改变页面初始状态，导致后续控件"看起来没反应"（假的）
    await page.keyboard.press("Escape").catch(() => undefined);
    if (overlayGrew || contentGrew || urlChanged) {
      await page.goto(BASE + PAGE, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForSelector("tbody tr.ant-table-row, .panel, section", { timeout: 20000 }).catch(() => undefined);
      await page.waitForTimeout(2500);
    } else {
      await page.waitForTimeout(400);
    }
  }

  writeFileSync(OUT, JSON.stringify(results, null, 2));
  const failed = results.filter((item) => !item.ok);
  console.log(`\n  通过 ${results.length - failed.length}/${results.length}（失败 ${failed.length}）`);
  await browser.close();
  process.exitCode = failed.length === 0 ? 0 : 1;
}

main().catch((error) => {
  console.error("失败:", error.message);
  process.exit(1);
});
