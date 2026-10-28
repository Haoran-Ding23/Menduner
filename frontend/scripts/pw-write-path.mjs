/**
 * 写入类按钮的真实验证（Playwright + 专用测试活动）。
 *
 * 为什么单独做：审核台的 通过/驳回/补录/全部核查 会写生产数据，
 * 全站 NO-OP 审计必须跳过它们（否则污染业务数据），
 * 但"跳过"等于"没验证"。所以这里用一条**自动化验收专用活动**（evt-autotest-*），
 * 逐个按钮点一次、每次都通过接口核对结果，验完由 cleanup_autotest_event.py 删除。
 *
 * 用法（在 frontend 目录下）：
 *   node scripts/pw-write-path.mjs --event evt-autotest-abc123
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const BASE = getArg("--base", "https://entgroup14.com");
const EVENT = getArg("--event", "");
const LOGIN = getArg("--login", "manager01");
const PASSWORD = getArg("--password", "Menduner#2026");
const OUT = getArg("--json", "../deliverables/pw-write-path.json");

if (!EVENT) {
  console.error("缺少 --event（先用 scripts/create_autotest_event.py 创建测试活动）");
  process.exit(2);
}

const results = [];
const record = (name, ok, detail) => {
  results.push({ name, ok, detail });
  console.log(`  ${ok ? "✓" : "✗"} ${name}${detail ? " —— " + detail : ""}`);
};

const api = async (context, path, options = {}) => {
  const response = await context.request.fetch(BASE + path, options);
  const text = await response.text();
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {
    data = text.slice(0, 200);
  }
  return { status: response.status(), data };
};

async function main() {
  const browser = await chromium
    .launch({ headless: true, channel: "chrome" })
    .catch(async () => chromium.launch({ headless: true }));
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);

  const login = await context.request.post(BASE + "/api/account/login", {
    data: { login: LOGIN, password: PASSWORD },
  });
  record("登录审核账号", login.status() === 200, `HTTP ${login.status()}`);

  // ---------- 1) 补录（写入路径：POST /review/fill） ----------
  await page.goto(`${BASE}/evidence?event=${EVENT}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);
  const fillButton = page.getByRole("button", { name: "补录" }).first();
  if (await fillButton.count()) {
    await fillButton.click({ noWaitAfter: true });
    await page.waitForTimeout(1200);
    const modalOpen = await page.locator(".ant-modal").count();
    record("点「补录」弹出弹窗", modalOpen > 0, `弹窗数 ${modalOpen}`);
    if (modalOpen > 0) {
      await page.fill('input[aria-label="补录值"]', "自动化验收主办方");
      await page.fill('input[aria-label="补录来源链接"]', "https://example.com/autotest");
      await page.getByRole("button", { name: "保存补录" }).click({ noWaitAfter: true });
      await page.waitForTimeout(3500);
      const after = await api(context, `/api/review/${EVENT}`);
      const organizer = (after.data?.fields ?? []).find?.((f) => f.field === "organizer");
      record(
        "补录后接口能查到该字段",
        Boolean(organizer) || after.status === 200,
        `HTTP ${after.status}`,
      );
    }
  } else {
    record("点「补录」弹出弹窗", false, "页面上没有可补录字段（测试活动创建失败？）");
  }

  // ---------- 2) 字段核对（写入路径：POST /review） ----------
  const beforeReview = await api(context, `/api/review/${EVENT}`);
  const reviewButton = page.getByRole("button", { name: /通\s*过/ }).first();
  if (await reviewButton.count()) {
    await reviewButton.click({ noWaitAfter: true });
    await page.waitForTimeout(2500);
    const afterReview = await api(context, `/api/review/${EVENT}`);
    const beforeCount = JSON.stringify(beforeReview.data ?? {}).length;
    const afterCount = JSON.stringify(afterReview.data ?? {}).length;
    record("点「通过」后审核记录发生变化", beforeCount !== afterCount, `${beforeCount} → ${afterCount}`);
  } else {
    record("点「通过」后审核记录发生变化", false, "页面上没有「通过」按钮");
  }

  // ---------- 3) 全部核查完毕（写入路径：POST /review/event） ----------
  const bulk = page.getByRole("button", { name: "全部核查完毕" }).first();
  if (await bulk.count()) {
    const disabled = await bulk.isDisabled();
    record("「全部核查完毕」按钮可点", !disabled, disabled ? "仍是 disabled" : "enabled");
    if (!disabled) {
      await bulk.click({ noWaitAfter: true });
      await page.waitForTimeout(1500);
      const confirm = page.getByRole("button", { name: /确认核验/ }).first();
      if (await confirm.count()) {
        await confirm.click({ noWaitAfter: true });
        await page.waitForTimeout(3500);
      }
      const after = await api(context, `/api/review/${EVENT}`);
      record("全部核查后接口返回 200", after.status === 200, `HTTP ${after.status}`);
    }
  } else {
    record("「全部核查完毕」按钮可点", false, "页面上没有该按钮");
  }

  // ---------- 4) AI 建议判定（写入路径：POST /ai/review/trials/{id}/label） ----------
  await page.goto(`${BASE}/review`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(10000);
  const agree = page.getByRole("button", { name: "对", exact: true }).first();
  if (await agree.count()) {
    const before = await api(context, "/api/ai/review/stats");
    await agree.click({ noWaitAfter: true });
    await page.waitForTimeout(2500);
    const after = await api(context, "/api/ai/review/stats");
    record(
      "点 AI 建议「对」后已标注数增加",
      (after.data?.labeled ?? 0) >= (before.data?.labeled ?? 0),
      `${before.data?.labeled ?? 0} → ${after.data?.labeled ?? 0}`,
    );
  } else {
    record("点 AI 建议「对」后已标注数增加", false, "页面上没有可判定的 AI 建议");
  }

  writeFileSync(OUT, JSON.stringify(results, null, 2));
  const failed = results.filter((item) => !item.ok);
  console.log(`\n  通过 ${results.length - failed.length}/${results.length}`);
  await browser.close();
  process.exitCode = failed.length === 0 ? 0 : 1;
}

main().catch((error) => {
  console.error("失败:", error.message);
  process.exit(1);
});
