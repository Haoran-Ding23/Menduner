# 前端错误 109 条:根因与修复(2026-10-17)

**结论**:109 条不是 109 个问题,而是**两个**:98 条是同一个系统性 bug(高德地图的
`_AMapService` 代理配置被打进生产包),11 条是一次性的部署缓存事故(2026-10-14 早上,
同一台鸿蒙手机,6 分钟内)。两处都已修掉,新错误不再产生。

---

## 一、错误构成(线上库全量)

| 消息 | 条数 | 页面 | 设备 |
|---|---|---|---|
| `SyntaxError: Unexpected token '<'` | **98** | /map 69、/hotels 24、/graph 11、其他 4 | 桌面 Edge 67、iPhone 6、鸿蒙 3、HeadlessChrome 4、扫描器 5 |
| `Unable to preload CSS for /assets/index-BnuhLJ6X.css` | **11** | /graph 11 | 同一台鸿蒙手机 `BRA-AL00`,全部在 2026-10-14 07:00–07:06(UTC) |

第一条**跨设备、跨日期**(10-14 到 10-17)反复出现 → 不是某个浏览器的问题,是页面本身。
第二条**只来自一台设备的一个 6 分钟窗口** → 典型的一次性缓存问题。

## 二、根因 1:开发用的高德代理路径进了生产包(98 条)

证据链,每一步都实测:

1. `frontend/.env.local` 里 `VITE_AMAP_SERVICE_HOST=/_AMapService` —— 这是给 **Vite 开发服务器**
   用的相对路径(见 `vite.config.ts` 里的 dev proxy)。
2. Vite 的 `.env.local` 对 **production build 同样生效**,于是这个值被打进了构建产物
   (`index-7Ls9UuLY.js` 里能找到 `_AMapService` / `serviceHost`)。
3. `src/components/Map/index.tsx` 当年把它直接塞给高德:
   `window._AMapSecurityConfig = { serviceHost: new URL(host, origin).href }`。
4. 生产环境 nginx 上没有任何 `/_AMapService` 代理,而 SPA 回退 `try_files … /index.html`
   会把这个路径**回答成 471 字节的 index.html**。nginx 访问日志原文:

   ```
   GET /_AMapService/v3/log/init?...&callback=jsonp_200916_1792212641771_ 200 471
   GET /_AMapService/v3/geocode/regeo?...                                  200 471
   GET /_AMapService/v4/map/styles                                         200 471
   ```

5. 高德 SDK 对其中一条用的是 **JSONP**(`callback=jsonp_…`,动态插入 `<script>`),浏览器把
   HTML 当 JavaScript 执行 → `SyntaxError: Unexpected token '<'`;另一条是 JSON 请求,同样拿到
   HTML。**每个带地图的页面固定 2 条**,与 `/map`、`/hotels` 的分布、每月每天重复出现完全吻合。

### 修法(三层,缺一不可)

- **前端**:`Map/index.tsx` 新增 `amapServiceHost(configured, {dev, origin})` —— 相对路径
  **只在开发环境**接受;生产环境只接受**另一个域的绝对代理地址**,否则返回 `null`、不设置
  `serviceHost`,让 SDK 直接请求高德(地图本体/标记/半径圈照常,仅自定义样式回退默认样式)。
- **nginx**:新增 `location ^~ /_AMapService/` —— 有 `callback` 参数时返回合法 JS,否则返回
  高德的错误信封 `{"status":"0","info":"AMAP_SERVICE_PROXY_NOT_CONFIGURED"}`。**任何情况下都
  不再返回 HTML**。这层专门保护还开着旧页面的访客和旧的缓存包。
- **错误记录器**:`window.error` 现在把浏览器给的 `filename / lineno / colno` 记进 `extra`
  (库表本来就有这一列,以前一直为空),前端错误页展开即可看到"出错文件"。这次的 98 条当时
  **没有任何一条**能指出是哪个请求失败,只能靠翻 nginx 日志反推 —— 以后不用了。

### 验证(真实浏览器,不是断言)

用本机 headless Edge(155.0.4283.45)通过 CDP 加载线上页面,收集 `Runtime.exceptionThrown`、
`console.error/warning`、`Log.entryAdded`:

```
http://47.116.133.230/map    → 1 条事件:AMap 的 Canvas2D 性能提示,无异常
http://47.116.133.230/hotels → 1 条事件:同上
```

- 修复前:`client_errors` 最新 id=115,时间 2026-10-17T04:50:42Z(用户 12:50 那次访问)。
- 修复后:再用 headless 浏览器访问 `/map`、`/hotels`,库仍是 **109 条、最新时间不变** → 没有新错误。
- nginx 日志:headless 访问期间**没有**新的 `/_AMapService` 请求(只剩我自己 curl 验证的 2 条),
  证明新包的 SDK 根本不再向那个路径发请求。

## 三、根因 2:一次性的部署缓存事故(11 条)

11 条全部是 `Unable to preload CSS for /assets/index-BnuhLJ6X.css`,全部来自同一台鸿蒙手机、
同一个 `/graph` 页面、2026-10-14 07:00–07:06(UTC)的 6 分钟。这是仓库里已经记录过的经典问题:
**浏览器缓存着上一版 `index.html`,它指向的带哈希的 CSS 在新部署里不存在了。** 现在有三重保护:

1. `deploy/deploy-frontend.sh` **从不删旧 assets**(只合并),并用"nginx 实际返回的 index.html"
   做校验,而不是只看源目录;
2. `location = /index.html` 强制 `no-cache, must-revalidate`(带哈希的资源才允许长缓存);
3. `location /assets/` 用 `try_files $uri =404`,缺资源时不会再拿 index.html 冒充。

那 11 条**无法复现也不该复现**,保留在库里作为历史记录。

## 四、以后再遇到"前端错误很多",按这个顺序看

1. 前端错误页展开一行,先看 **消息是否都一样** —— 这次的 98 条就是同一个 bug。
2. 看 **页面分布**(带地图的页面?)、**设备分布**(一台设备 = 自己的缓存问题;所有设备 = 代码问题)。
3. 展开看 **出错文件(filename:line:col)** 或堆栈第一条。
4. 对照 nginx 访问日志里同一时间的异常请求(状态 200 但 body 是 HTML 就是典型信号)。

## 五、没有做的事

- **没有删除历史 109 条**:它们是这次判断的依据,保留在库里;页面只显示最新 50 条,不会再增长。
- 那 11 条 CSS 错误**没有"修复"可言**:它们发生在 10-14,当时的部署没有保留旧 assets,
  现在的部署方式已经不会产生同类问题。
