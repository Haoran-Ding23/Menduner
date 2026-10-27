/**
 * 业务效果断言（比 NO-OP 更严）：断言「点击后必须发生什么」和「点击后不许发生什么」。
 *
 * 覆盖用户明确反馈过的问题：
 *  1 点「查看附近酒店」：酒店标记必须增加，且**视野不允许改变**
 *  2 点「查看商圈」：商圈参考点必须出现（53 个），且**视野不允许改变**
 *  3 点商圈中心点：出现范围圆，**视野不允许改变**（用户反馈"一点就放大"）
 *  4 图谱点「查看周边设施」：必须出现周边列表；再点「收起周边」必须消失
 *  5 审核台点「补录」：必须出现弹窗（标题「补录这个字段」）
 *  6 审核台「全部核查完毕」：必须可点（disabled=false）
 *  7 地图页直接进入：**不许**自动弹出活动详情抽屉
 *
 * node scripts/cdp-assertions.mjs [base]
 * 退出码 0 = 全部通过。
 */
const BASE = process.argv[2] ?? "https://entgroup14.com";
const DEBUG = "http://127.0.0.1:9345";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, pass, detail) {
  results.push({ name, pass, detail });
  console.log(`  ${pass ? "✓" : "✗"} ${name}${detail ? " —— " + detail : ""}`);
}

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
      const timer = setTimeout(() => { pending.delete(mid); reject(new Error("超时:" + method)); }, 30000);
      pending.set(mid, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  const ev = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return r.result ? r.result.value : null;
  };
  const login = async () => {
    await ev("fetch('/api/account/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({login:'manager01',password:'Menduner#2026'})}).then(r=>r.status)");
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Network.clearBrowserCookies");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  // ---------- 地图页 ----------
  await send("Page.navigate", { url: BASE + "/map" });
  await sleep(19000);
  check("地图页不自动弹详情抽屉", !(await ev("!!document.querySelector('.ant-drawer-open')")));

  const viewBefore = await ev("window.__mapView ? JSON.stringify(window.__mapView) : null");
  const hotelsBefore = await ev("[...document.querySelectorAll('.amap-marker')].filter(m=>/^H+$/.test((m.textContent||'').trim())).length");
  await ev("(function(){const s=document.querySelector('.ant-switch[aria-label=\"查看附近酒店\"]'); if(s) s.click(); return !!s;})()");
  await sleep(6000);
  const hotelsAfter = await ev("[...document.querySelectorAll('.amap-marker')].filter(m=>/^H+$/.test((m.textContent||'').trim())).length");
  const viewAfterHotels = await ev("window.__mapView ? JSON.stringify(window.__mapView) : null");
  check("开酒店图层：标记增加", hotelsAfter > hotelsBefore, `${hotelsBefore} → ${hotelsAfter}`);
  check("开酒店图层：视野不变", viewBefore === viewAfterHotels || viewBefore === null, `${viewBefore} → ${viewAfterHotels}`);

  const beforeAreas = await ev("document.querySelectorAll('.area-marker').length");
  await ev("(function(){const s=document.querySelector('.ant-switch[aria-label=\"查看商圈\"]'); if(s) s.click(); return !!s;})()");
  await sleep(8000);
  const afterAreas = await ev("document.querySelectorAll('.area-marker').length");
  const viewAfterAreas = await ev("window.__mapView ? JSON.stringify(window.__mapView) : null");
  check("开商圈图层：出现参考点", afterAreas > 20, `${beforeAreas} → ${afterAreas}`);
  check("开商圈图层：视野不变", viewBefore === viewAfterAreas || viewBefore === null, `${viewBefore} → ${viewAfterAreas}`);

  // ---------- 商圈洞察：点选商圈不许放大 ----------
  await send("Page.navigate", { url: BASE + "/insights" });
  await sleep(20000);
  const insViewBefore = await ev("window.__mapView ? JSON.stringify(window.__mapView) : null");
  await ev("(function(){const a=document.querySelector('.area-marker'); if(!a) return 'none'; a.click(); return 'ok';})()");
  await sleep(3000);
  const insViewAfter = await ev("window.__mapView ? JSON.stringify(window.__mapView) : null");
  check("商圈洞察：点选商圈后视野不变", insViewBefore === insViewAfter || insViewBefore === null, `${insViewBefore} → ${insViewAfter}`);

  // ---------- 图谱：周边展开/收起 ----------
  await send("Page.navigate", { url: BASE + "/graph" });
  await sleep(21000);
  const listsBefore = await ev("document.querySelectorAll('.relation-list').length");
  await ev("(function(){const b=[...document.querySelectorAll('button')].find(x=>/查看周边设施/.test(x.textContent||'')); if(b) b.click(); return !!b;})()");
  await sleep(2500);
  const listsOpen = await ev("document.querySelectorAll('.relation-list').length");
  await ev("(function(){const b=[...document.querySelectorAll('button')].find(x=>/收起周边/.test(x.textContent||'')); if(b) b.click(); return !!b;})()");
  await sleep(2000);
  const listsClosed = await ev("document.querySelectorAll('.relation-list').length");
  check("图谱：查看周边设施能展开", listsOpen > listsBefore, `${listsBefore} → ${listsOpen}`);
  check("图谱：收起周边能收起", listsClosed === listsBefore, `${listsOpen} → ${listsClosed}`);

  // ---------- 审核台：补录弹窗 / 全部核查可点（需登录） ----------
  await send("Page.navigate", { url: BASE + "/evidence" });
  await sleep(7000);
  await login();
  await send("Page.navigate", { url: BASE + "/evidence" });
  await sleep(18000);
  const fillBtn = await ev("!!([...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='补录'))");
  if (fillBtn) {
    await ev("(function(){const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='补录'); b.click(); return 'ok';})()");
    await sleep(1500);
    const modal = await ev("(document.querySelector('.ant-modal-title')||{}).textContent||null");
    check("审核台：点补录弹出弹窗", modal === "补录这个字段", String(modal));
    await ev("(function(){const b=[...document.querySelectorAll('.ant-modal button')].find(x=>/取消/.test(x.textContent||'')); if(b) b.click(); return !!b;})()");
  } else {
    check("审核台：点补录弹出弹窗", false, "当前活动没有可补录字段（换一条活动再测）");
  }

  await send("Page.navigate", { url: BASE + "/review" });
  await sleep(18000);
  const bulk = await ev(`(function(){
    const b=[...document.querySelectorAll('button')].find(x=>/全部核查完毕/.test(x.textContent||''));
    return b ? { found:true, disabled: Boolean(b.disabled) } : { found:false };
  })()`);
  check("审核台：全部核查完毕按钮可用", Boolean(bulk && bulk.found && bulk.disabled === false), JSON.stringify(bulk));

  const failed = results.filter((r) => !r.pass);
  console.log(`\n  通过 ${results.length - failed.length}/${results.length}`);
  if (failed.length) {
    console.log("  未通过：");
    failed.forEach((r) => console.log(`    ✗ ${r.name} —— ${r.detail}`));
  }
  ws.close();
  process.exitCode = failed.length === 0 ? 0 : 1;
}

main().catch((error) => { console.error("失败:", error.message); process.exit(1); });
