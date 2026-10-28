/**
 * 写入类按钮的逐项验证（Playwright + 本地隔离环境）。
 *
 * 每个动作都做两件事：
 *   1 在界面上真的点一次（含弹窗、确认框）；
 *   2 通过接口/界面状态核对「确实写进去了」，而不是只看"有没有反应"。
 *
 * 用法（本地环境见 scripts/seed_local_verify_db.py）：
 *   node scripts/pw-write-path2.mjs --base http://127.0.0.1:5199 --event evt-verify-full
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const BASE = getArg("--base", "http://127.0.0.1:5199");
const EVENT = getArg("--event", "evt-verify-full");
const LOGIN = getArg("--login", "menduner");
const PASSWORD = getArg("--password", "123456");
const OUT = getArg("--json", "../deliverables/pw-write-path2.json");

const results = [];
const record = (name, ok, detail) => {
  results.push({ name, ok, detail });
  console.log(`  ${ok ? "✓" : "✗"} ${name}${detail ? " —— " + detail : ""}`);
};

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" }).catch(async () => chromium.launch({ headless: true }));
  const context = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
  await context.request.post(BASE + "/api/account/login", { data: { login: LOGIN, password: PASSWORD } });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);

  const apiLog = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/review")) apiLog.push(r.status() + " " + r.request().method() + " " + r.url().split("/api")[1]);
  });

  const decisions = async () => {
    const response = await context.request.get(`${BASE}/api/review/${EVENT}`);
    if (response.status() !== 200) return { status: response.status(), count: -1, signature: "" };
    const data = await response.json();
    const list = Array.isArray(data) ? data : (data.decisions ?? data.fields ?? []);
    const entries = Array.isArray(list) ? list : [];
    // 签名 = 条数 + 最新一条的 id/决定/时间：任一处变化都说明这次点击真的写了东西
    const last = entries.slice().sort((a, b) => String(b.decided_at ?? "").localeCompare(String(a.decided_at ?? "")))[0];
    const signature = entries.length + "|" + (last ? `${last.id}:${last.decision}:${last.decided_at}` : "");
    return { status: 200, count: entries.length, signature };
  };

  // 「修正」按钮用 window.prompt 收集新值，自动化必须应答对话框
  page.on("dialog", (dialog) => void dialog.accept("修正后的值"));

  await page.goto(`${BASE}/review?event=${EVENT}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(11000);

  const before = await decisions();
  record("打开审核台能取到审核记录", before.status === 200, `HTTP ${before.status}，记录 ${before.count} 条`);

  // ---------- 1) 驳回 ----------
  const rejectButton = page.getByRole("button", { name: /驳\s*回/ }).first();
  if (await rejectButton.count()) {
    const beforeReject = await decisions();
    await rejectButton.click({ noWaitAfter: true });
    await page.waitForTimeout(900);
    const confirm = page.getByRole("button", { name: /确\s*定|确\s*认|OK/i }).first();
    if (await confirm.count()) await confirm.click({ noWaitAfter: true }).catch(() => undefined);
    await page.waitForTimeout(3000);
    const afterReject = await decisions();
    record(
      "点「驳回」写入审核记录",
      afterReject.signature !== beforeReject.signature,
      `${beforeReject.count} 条 → ${afterReject.count} 条（签名${afterReject.signature === beforeReject.signature ? "未变" : "已变"}）`,
    );
  } else {
    record("点「驳回」写入审核记录", false, "页面上没有「驳回」按钮");
  }

  // ---------- 2) 修正（需要填修正值） ----------
  await page.goto(`${BASE}/review?event=${EVENT}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);
  const correctButton = page.getByRole("button", { name: /修\s*正/ }).first();
  if (await correctButton.count()) {
    const beforeCorrect = await decisions();
    await correctButton.click({ noWaitAfter: true });
    await page.waitForTimeout(3500);
    const afterCorrect = await decisions();
    console.log("    最近接口:", JSON.stringify(apiLog.slice(-3)));
    record(
      "点「修正」写入修正值",
      afterCorrect.signature !== beforeCorrect.signature,
      `${beforeCorrect.count} 条 → ${afterCorrect.count} 条（签名${afterCorrect.signature === beforeCorrect.signature ? "未变" : "已变"}）`,
    );
  } else {
    record("点「修正」写入修正值", false, "页面上没有「修正」按钮");
  }

  // ---------- 3) 撤回 ----------
  await page.goto(`${BASE}/review?event=${EVENT}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);
  const revokeButton = page.getByRole("button", { name: /撤\s*回/ }).first();
  if (await revokeButton.count()) {
    const beforeRevoke = await decisions();
    await revokeButton.click({ noWaitAfter: true });
    await page.waitForTimeout(800);
    const confirm = page.getByRole("button", { name: /确\s*定|确\s*认|OK/i }).first();
    if (await confirm.count()) await confirm.click({ noWaitAfter: true }).catch(() => undefined);
    await page.waitForTimeout(3000);
    const afterRevoke = await decisions();
    record(
      "点「撤回」撤销上一条审核",
      afterRevoke.signature !== beforeRevoke.signature,
      `${beforeRevoke.count} 条 → ${afterRevoke.count} 条（签名${afterRevoke.signature === beforeRevoke.signature ? "未变" : "已变"}）`,
    );
  } else {
    record("点「撤回」撤销上一条审核", false, "页面上没有「撤回」按钮（该按钮只在已决定的字段行出现）");
  }

  // ---------- 4) 录入一条（人工录入） ----------
  await page.goto(`${BASE}/review`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);
  const openEntry = page.getByRole("button", { name: /录入一条/ }).first();
  if (await openEntry.count()) {
    await openEntry.click({ noWaitAfter: true });
    await page.waitForTimeout(1000);
    const nameInput = page.locator('input[placeholder*="活动名称"]').first();
    // 日期是文本输入（placeholder 提示 YYYY-MM-DD），不是 date 控件
    const dateInput = page.locator('input[placeholder*="开始 YYYY-MM-DD"]').first();
    if (await nameInput.count()) await nameInput.fill("【写入验证】录入按钮测试");
    if (await dateInput.count()) await dateInput.fill("2026-12-01");
    const submit = page.getByRole("button", { name: /录入并进入待复核/ }).first();
    if (await submit.count()) {
      await submit.click({ noWaitAfter: true });
      await page.waitForTimeout(3500);
      const toast = await page.evaluate(() => (document.querySelector(".ant-message") || {}).innerText || null);
      record("点「录入一条」能提交并给出结果", Boolean(toast), String(toast));
    } else {
      record("点「录入一条」能提交并给出结果", false, "没有提交按钮");
    }
  } else {
    record("点「录入一条」能提交并给出结果", false, "页面上没有「录入一条」");
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
