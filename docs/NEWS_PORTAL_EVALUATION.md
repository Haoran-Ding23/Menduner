# 新闻门户来源评估（搜狐 / 新浪 / 今日头条）

评估日期：2026-10-15 · 目的：判断能否从新闻门户获取苏州活动信息

## 结论

**三个来源全部不可用，且失败原因各不相同。** 两个 robots.txt 明确禁止，第三个虽然 robots 开放但没有活动内容。

| 来源 | robots.txt | 内容 | 判定 |
|---|---|---|---|
| 搜狐 sohu.com | **`User-agent: *` → `Disallow: /`** | — | **禁止** |
| 今日头条 toutiao.com | 部分禁止（文章页被禁） | 首页仅 28 个可见字符（JS 空壳） | **不可用** |
| 新浪 sina.com.cn | `User-agent: *` → `Allow: /`（**开放**） | 无苏州活动内容 | **无内容** |

## 逐条明细

### 搜狐 —— robots.txt 全站禁止

搜狐的 robots.txt 采用分组白名单结构：

```
User-agent: Baiduspider / Googlebot / bingbot / ...
    Allow: /a/*?*  /cul*?*  /travel*?*  ...
    Disallow: /*?*

User-agent: GPTBot / ClaudeBot / DeepSeekBot / FirecrawlAgent / ...
    Disallow: /

User-agent: *          ← 最后一组
    Disallow: /        ← 全部禁止
```

**未列入白名单的爬虫命中 `User-agent: *` 的 `Disallow: /`，一律禁止。** 我们不在白名单里。

值得注意：搜狐**专门列出了 AI 爬虫并全部禁止**（GPTBot、ClaudeBot、DeepSeekBot、FirecrawlAgent 等）。这一层的规则很清楚，也不需要试探。

### 今日头条 —— 文章页被 disallow

```
User-agent: *
Disallow: /search
Disallow: /item/      ← 文章页
Disallow: /group/     ← 文章页
Disallow: /trending/
...
```

**文章页（`/item/`、`/group/`）和搜索页（`/search`）都被禁止。** 首页未被禁止，但它是纯 JS 空壳：HTML 4883 字符，**可见文字仅 28 个字符**，没有内容可提取。

**即使首页允许抓取，上面也没有活动。** 头条的内容在 `/item/`，而那正是被禁止的路径。

### 新浪 —— robots 开放，但没有活动

```
User-agent: *
Allow: /
Sitemap: https://www.sina.com.cn/sitemap/index.xml
```

**这是三个里唯一明确开放的。** 但实测内容为空：

| 页面 | 可见文字 | 含「苏州」 |
|---|---:|---:|
| `news.sina.com.cn/` | 12,701 字符 | **1 次** |
| `jiangsu.sina.com.cn/` | 1 字符 | 0 次 |
| `jiangsu.sina.com.cn/travel/` | 31 字符 | 0 次 |
| `jiangsu.sina.com.cn/city/` | 31 字符 | 0 次 |
| `news.sina.com.cn/zt/` | 4,117 字符 | 0 次 |
| `suzhou.sina.com.cn/` | — | 域名不存在（DNS 失败） |

**新浪江苏频道和它下面的旅游、城市栏目都是 JS 渲染的空壳。** 新闻首页虽然内容完整，但苏州只出现 1 次，且是新闻而非活动日程。

**新浪没有苏州活动栏目。**

## 为什么新闻门户不适合这个用途

这三家都是**新闻聚合门户**，不是**活动来源**。两者发布的内容性质不同：

| | 新闻门户 | 活动来源（场馆/政府文旅/票务） |
|---|---|---|
| 内容 | 事件发生后的报道 | 活动举办前的日程 |
| 字段 | 时间、地点散落在正文 | 日期、场馆、主办方是结构化字段 |
| 时效 | 报道已发生的事 | 预告未来的事 |
| 日期形态 | 发稿日期 | **活动举办日期** |

**你的项目需要的是「未来有什么活动」，而新闻门户提供的是「过去发生了什么」。** 即使抓到了，也拿不到可用的活动日期。

而且新闻门户属于 `SECONDARY_MEDIA` 信任等级 —— **即使抓到活动，也只能进人工复核队列，无法自动核验。**

## 与「大麦」的一致处理

本次评估与大麦的处理方式相同：**在写代码之前先查 robots.txt**，得到否定结论就记录原因并停止，不尝试绕过。

这延续了项目里已有的边界（见 V1.6_SOURCE_COVERAGE_REPORT.md）：

> no pagination, browser automation, login, CAPTCHA solving, mobile app crawling, token access or protected API bypass was introduced

## 未做的事

- **没有请求被 robots.txt 禁止的路径**（搜狐任何路径、头条的 `/item/`、`/group/`、`/search`）
- **没有使用浏览器自动化**去渲染 JS 空壳页面
- **没有伪造 User-Agent** 冒充搜索引擎爬虫
- **没有使用搜索快照或缓存**作为活动记录
- **没有向注册表添加来源** —— 三个来源都没进入 `source_registry.yaml`，因为没有可抓的路径

## 如果后续需要苏州活动信息

已验证可行的方向（按优先级）：

1. **场馆官网** —— 属于 `OFFICIAL_VENUE`，**能自动核验**。已实测苏州国际博览中心官网渲染后有 100 场展会日程
2. **政府文旅局** —— 属于 `OFFICIAL_GOVERNMENT`，能自动核验
3. **人工录入 + 附原始链接** —— 系统正式支持的 `manual_only` 路径，零风险

**新闻门户不在这个列表里，因为它们的失败原因不是技术性的，而是「这类网站不发布活动日程」。**
