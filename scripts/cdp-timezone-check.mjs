/**
 * F03 证据脚本：把页面时钟固定到「北京已跨日、纽约还没跨日」的时刻，在三种时区下读页面
 * 渲染出的「今天」。
 *
 * 为什么必须固定时钟：审核是在 UTC 2026-10-23T22:03 观察到分歧的（北京 10-24、纽约 10-23）。
 * 如果只在当前真实时间下对比，三地很可能同一天，测不出问题。
 *
 * 做法：用 CDP 的 Page.addScriptToEvaluateOnNewDocument 在页面脚本执行前把 Date 固定到该时刻，
 * 再用 Emulation.setTimezoneOverride 切换设备时区。业务日期若正确取自 Asia/Shanghai，三种
 * 时区下都应该是 2026-10-24。
 *
 * 用法（先以 --remote-debugging-port 启动 Chrome）：
 *   node scripts/cdp-timezone-check.mjs http://127.0.0.1:5213
 */

const BASE = process.argv[2] ?? "http://127.0.0.1:5213";
const DEBUG = process.argv[3] ?? "http://127.0.0.1:9333";
const FIXED_INSTANT = "2026-10-23T22:03:00Z";
const EXPECTED = "2026-10-24";
const ZONES = ["America/New_York", "Asia/Shanghai", "UTC"];

const WATCHDOG = setTimeout(() => {
  console.error("看门狗触发：脚本超过 120 秒未完成，判定为卡死");
  process.exit(2);
}, 120000);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function firstPage() {
  const response = await fetch(`${DEBUG}/json/list`);
  const pages = (await response.json()).filter((item) => item.type === "page");
  if (!pages.length) throw new Error("没有可用的页面目标");
  return pages[0];
}

function connect(url) {
  const socket = new WebSocket(url);
  let id = 0;
  const pending = new Map();

  const ready = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("WebSocket 握手超时")), 10000);
    socket.addEventListener("open", () => {
      clearTimeout(timeout);
      resolve();
    });
    socket.addEventListener("error", () => {
      clearTimeout(timeout);
      reject(new Error("WebSocket 连接失败"));
    });
  });

  socket.addEventListener("message", async (event) => {
    // Node 内置 WebSocket 可能给出 string / Blob / ArrayBuffer；只认 string 会静默丢帧。
    let raw;
    if (typeof event.data === "string") raw = event.data;
    else if (event.data instanceof Blob) raw = await event.data.text();
    else raw = Buffer.from(event.data).toString("utf8");
    const payload = JSON.parse(raw);
    const entry = payload.id ? pending.get(payload.id) : null;
    if (!entry) return;
    pending.delete(payload.id);
    payload.error ? entry.reject(new Error(payload.error.message)) : entry.resolve(payload.result);
  });

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const messageId = ++id;
      const timer = setTimeout(() => {
        pending.delete(messageId);
        reject(new Error("CDP 命令超时：" + method));
      }, 20000);
      pending.set(messageId, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      socket.send(JSON.stringify({ id: messageId, method, params }));
    });

  return { ready, send, close: () => socket.close() };
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  return result.result?.value;
}

async function goto(client, url) {
  await client.send("Page.navigate", { url });
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await sleep(250);
    const heading = await evaluate(client, "document.querySelector('h1')?.textContent ?? ''");
    if (heading && heading.trim()) return heading.trim();
  }
  throw new Error("页面没有渲染出标题：" + url);
}

/** 在页面脚本执行前把 Date 固定到一个具体时刻。 */
const FIXED_CLOCK = `
(() => {
  const FIXED = Date.parse("${FIXED_INSTANT}");
  const RealDate = Date;
  function FakeDate(...args) {
    if (args.length === 0) return new RealDate(FIXED);
    return new RealDate(...args);
  }
  FakeDate.now = () => FIXED;
  FakeDate.parse = RealDate.parse;
  FakeDate.UTC = RealDate.UTC;
  FakeDate.prototype = RealDate.prototype;
  window.Date = FakeDate;
})();
`;

/** 活动清单里「今天」那一行渲染出的日期。 */
const AGENDA_TODAY = [
  "(function () {",
  "  const leaves = Array.from(document.querySelectorAll('*')).filter((n) => n.children.length === 0);",
  "  const label = leaves.find((n) => n.textContent.trim() === '今天');",
  "  if (!label) return null;",
  "  let node = label;",
  "  for (let i = 0; i < 4 && node; i += 1) {",
  "    const match = (node.textContent || '').match(/\\d{4}-\\d{2}-\\d{2}/);",
  "    if (match) return match[0];",
  "    node = node.parentElement;",
  "  }",
  "  return null;",
  "})()",
].join("\n");

/** 工作台口径条里的「未来 7 天」起止。 */
const WORKBENCH_WINDOW = [
  "(function () {",
  "  const match = document.body.innerText.match(/未来 7 天（(\\d{4}-\\d{2}-\\d{2}) 至 (\\d{4}-\\d{2}-\\d{2})）/);",
  "  return match ? { start: match[1], end: match[2] } : null;",
  "})()",
].join("\n");

/** 页面里 Date 是否真的被固定住了（自证）。 */
const CLOCK_PROBE = "new Date().toISOString()";

async function main() {
  const page = await firstPage();
  const client = connect(page.webSocketDebuggerUrl);
  await client.ready;
  await client.send("Page.enable");
  await client.send("Runtime.enable");
  await client.send("Page.addScriptToEvaluateOnNewDocument", { source: FIXED_CLOCK });
  console.log("页面时钟已固定到 " + FIXED_INSTANT + "（北京 " + EXPECTED + "，纽约 2026-10-23）");

  const rows = [];
  for (const zone of ZONES) {
    process.stdout.write("  " + zone + " ... ");
    await client.send("Emulation.setTimezoneOverride", { timezoneId: zone });
    await goto(client, `${BASE}/agenda`);
    const clock = await evaluate(client, CLOCK_PROBE);
    const agendaToday = await evaluate(client, AGENDA_TODAY);
    await goto(client, `${BASE}/workbench`);
    const workbench = await evaluate(client, WORKBENCH_WINDOW);
    const currentZone = await evaluate(client, "Intl.DateTimeFormat().resolvedOptions().timeZone");
    rows.push({
      时区: zone,
      浏览器认到: currentZone,
      页面时钟: clock,
      清单的今天: agendaToday,
      窗口起: workbench ? workbench.start : null,
    });
    console.log("完成");
  }

  await client.send("Emulation.setTimezoneOverride", { timezoneId: "" });
  client.close();
  console.table(rows);

  const allExpected =
    rows.every((row) => row.清单的今天 === EXPECTED) &&
    rows.every((row) => row.窗口起 === EXPECTED);
  console.log(
    allExpected
      ? "\n[PASS] F03：固定时钟下三种设备时区都得到「今天 = " + EXPECTED + "」，工作台窗口起点一致"
      : "\n[FAIL] F03：今天=" + rows.map((row) => row.清单的今天).join(" / ") +
          "，窗口起=" + rows.map((row) => row.窗口起).join(" / "),
  );
  return allExpected ? 0 : 1;
}

main()
  .then((code) => {
    clearTimeout(WATCHDOG);
    process.exitCode = code;
  })
  .catch((error) => {
    clearTimeout(WATCHDOG);
    console.error("脚本失败:", error.message);
    process.exitCode = 1;
  });
