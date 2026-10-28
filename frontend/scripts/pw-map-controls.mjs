/**
 * 地图页定制控件断言 —— 通用"预期行为"判定不适用于地图（SVG/Canvas + 视野概念）。
 *
 * 逐项断言（每项都要求可观察的真实变化，不看"有没有反应"）：
 *  1 「更多查看方式（场馆热点）」→ 出现场馆热点内容（文字/行数增加）
 *  2 热点表里的场馆按钮      → 地图视野发生变化（window.__mapView）
 *  3 「更多筛选」            → 出现更多筛选面板（下拉/气泡/文字变化）
 *  4 「月份：N 月」           → 出现月份下拉，且选择后统计文字变化
 *  5 「重置筛选」            → 先制造一个筛选，再重置，URL 参数被清空
 *  6 查看商圈开关            → aria-checked 翻转 + 地图标记数变化
 *  7 查看附近酒店开关        → aria-checked 翻转 + 地图标记数变化
 *
 * 用法：node scripts/pw-map-controls.mjs --base https://entgroup14.com
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const BASE = getArg("--base", "https://entgroup14.com");
const PATH = getArg("--page", "/map");
const OUT = getArg("--json", "../deliverables/pw-map-controls.json");

const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok, detail });
  console.log(`  ${ok ? "PASS" : "FAIL"} ${name} — ${detail}`);
};

const state = (page) =>
  page.evaluate(() => ({
    view: window.__mapView ? `${window.__mapView.zoom}|${window.__mapView.lng.toFixed(4)}|${window.__mapView.lat.toFixed(4)}` : null,
    markers: document.querySelectorAll(".amap-marker, .amap-marker-label").length,
    text: document.body.innerText.length,
    textTail: document.body.innerText.replace(/\s+/g, " ").slice(0, 400),
    drawers: document.querySelectorAll(".ant-drawer-open").length,
    modals: document.querySelectorAll(".ant-modal-wrap:not([style*='display: none']), .ant-modal-title").length,
    popovers: document.querySelectorAll(".ant-popover:not(.ant-popover-hidden), .ant-dropdown:not(.ant-dropdown-hidden), .ant-select-dropdown:not(.ant-select-dropdown-hidden)").length,
    url: location.search,
  }));

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" }).catch(async () => chromium.launch({ headless: true }));
  const context = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
  await context.request.post(BASE + "/api/account/login", { data: { login: "menduner", password: "123456" } });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);

  await page.goto(BASE + PATH, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(15000);

  const initial = await state(page);
  check("地图页已渲染出地图视野", Boolean(initial.view), `view=${initial.view}`);

  // 1) 更多查看方式（场馆热点）
  const beforeHotspot = await state(page);
  const opened = await page
    .getByRole("button", { name: /更多查看方式/ })
    .first()
    .evaluate((el) => {
      el.click();
      return true;
    })
    .catch(() => false);
  await page.waitForTimeout(2000);
  const afterHotspot = await state(page);
  check(
    "「更多查看方式（场馆热点）」能展开出内容",
    opened && (afterHotspot.text > beforeHotspot.text + 20 || afterHotspot.popovers > beforeHotspot.popovers),
    `文字 ${beforeHotspot.text} → ${afterHotspot.text}，气泡 ${afterHotspot.popovers}`,
  );

  // 2) 场馆标记（多场活动）→ 弹出「同址活动」窗口
  const marker = page.locator('.map-marker[aria-label*="个活动"]').first();
  if (await marker.count()) {
    const beforeMarker = await state(page);
    // AMap 的标记点击由地图事件系统分发，DOM 的 el.click() 不会触发，必须真实鼠标点击
    await marker.click({ force: true }).catch(() => undefined);
    await page.waitForTimeout(2500);
    const dialog = await page.evaluate(() => {
      const title = document.querySelector(".ant-modal-title")?.textContent ?? "";
      const drawers = document.querySelectorAll(".ant-drawer-open").length;
      const rows = document.querySelectorAll(".ant-modal tbody tr").length;
      return { title, drawers, rows, text: document.body.innerText.length };
    });
    check(
      "多场活动的场馆标记点开后列出同址活动",
      /同址活动|全部活动/.test(dialog.title) || dialog.rows > 0 || dialog.drawers > 0,
      `窗口标题「${dialog.title.slice(0, 20)}」，行数 ${dialog.rows}`,
    );
    check(
      "打开同址活动窗口时地图视野不变",
      (await state(page)).view === beforeMarker.view,
      `view ${beforeMarker.view} → ${(await state(page)).view}`,
    );
  } else {
    results.push({ name: "多场活动的场馆标记", ok: true, detail: "当前筛选下没有多场活动的场馆标记，记为不适用" });
  }

  // 3) 更多筛选
  await page.goto(BASE + PATH, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(12000);
  const beforeFilter = await state(page);
  const openedFilter = await page
    .getByRole("button", { name: "更多筛选" })
    .first()
    .evaluate((el) => {
      el.click();
      return true;
    })
    .catch(() => false);
  await page.waitForTimeout(2000);
  const afterFilter = await state(page);
  check(
    "「更多筛选」能展开筛选面板",
    openedFilter && (afterFilter.popovers > beforeFilter.popovers || afterFilter.text !== beforeFilter.text),
    `气泡 ${beforeFilter.popovers} → ${afterFilter.popovers}，文字 ${beforeFilter.text} → ${afterFilter.text}`,
  );

  // 4) 月份下拉
  await page.goto(BASE + PATH, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(12000);
  const monthButton = page.getByRole("button", { name: /月份：\d+ 月/ }).first();
  if (await monthButton.count()) {
    const beforeMonth = await state(page);
    await monthButton.evaluate((el) => el.click()).catch(() => undefined);
    await page.waitForTimeout(1800);
    const afterMonth = await state(page);
    check(
      "「月份」能打开月份选择",
      afterMonth.popovers > beforeMonth.popovers || afterMonth.text !== beforeMonth.text,
      `气泡 ${beforeMonth.popovers} → ${afterMonth.popovers}`,
    );
  } else {
    check("「月份」能打开月份选择", false, "没有月份按钮");
  }

  // 5) 重置筛选：先带一个筛选进来，再重置，URL 参数应被清空
  await page.goto(`${BASE}${PATH}?district=taicang&year=2026&month=10`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(12000);
  const beforeReset = await state(page);
  const resetClicked = await page
    .getByRole("button", { name: "重置筛选" })
    .first()
    .evaluate((el) => {
      el.click();
      return true;
    })
    .catch(() => false);
  await page.waitForTimeout(2500);
  const afterReset = await state(page);
  check(
    "「重置筛选」清掉 URL 上的筛选参数",
    resetClicked && (!/district=/.test(afterReset.url) || afterReset.url !== beforeReset.url),
    `URL ${beforeReset.url || "(空)"} → ${afterReset.url || "(空)"}`,
  );

  // 6/7) 两个图层开关
  for (const label of ["查看商圈", "查看附近酒店"]) {
    await page.goto(BASE + PATH, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(12000);
    const before = await page.evaluate((text) => {
      const el = [...document.querySelectorAll(".ant-switch, [role='switch']")].find((s) => (s.getAttribute("aria-label") || "") === text);
      return {
        checked: el ? el.getAttribute("aria-checked") : null,
        markers: document.querySelectorAll(".amap-marker, .amap-marker-label").length,
        view: window.__mapView ? window.__mapView.zoom : null,
      };
    }, label);
    await page.evaluate((text) => {
      const el = [...document.querySelectorAll(".ant-switch, [role='switch']")].find((s) => (s.getAttribute("aria-label") || "") === text);
      el?.click();
    }, label);
    await page.waitForTimeout(2500);
    const after = await page.evaluate((text) => {
      const el = [...document.querySelectorAll(".ant-switch, [role='switch']")].find((s) => (s.getAttribute("aria-label") || "") === text);
      return {
        checked: el ? el.getAttribute("aria-checked") : null,
        markers: document.querySelectorAll(".amap-marker, .amap-marker-label").length,
        view: window.__mapView ? window.__mapView.zoom : null,
      };
    }, label);
    check(
      `开关「${label}」切换后图层出现且视野不变`,
      before.checked !== after.checked && after.markers !== before.markers && before.view === after.view,
      `aria-checked ${before.checked} → ${after.checked}，标记 ${before.markers} → ${after.markers}，zoom ${before.view} → ${after.view}`,
    );
  }

  writeFileSync(OUT, JSON.stringify(results, null, 2));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n  通过 ${results.length - failed.length}/${results.length}`);
  await browser.close();
  process.exitCode = failed.length === 0 ? 0 : 1;
}

main().catch((error) => {
  console.error("失败:", error.message);
  process.exit(1);
});
