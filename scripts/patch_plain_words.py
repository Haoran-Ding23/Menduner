"""便民化第 2 轮（GPT Round 25 的 P0-3 / P0-4）：把内部话术换成客户能懂的话。

用户原话：推荐卡片上写着「2/4 个关键字段有来源 · 未知：缺少地区、来源核验」，这是内部质检话术。

改法（GPT 方案：主界面说人话，点击说明讲准确口径）：
1. 维度分数（相关性 1.00 · 距离 0.96 …）收进 tooltip，主界面只给两句话：
   「值得关注：高/中/低」「信息可靠：高/中/低」
2. 「2/4 个关键字段有来源」→「关键信息有 2 项可查证」
3. 「未知：缺少地区、来源核验」→「还没确认：地区、来源核验」
4. 分档规则写进 tooltip，避免变成"黑箱打分"
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---- ranking.ts 理由文案 ----
ranking = root / "frontend" / "src" / "services" / "ranking.ts"
r = ranking.read_text(encoding="utf-8")
r = r.replace(
    'reason: `${ok}/${checks.length} 个关键字段有来源（${checks.filter((c) => c.ok).map((c) => c.label).join("',
    'reason: `关键信息有 ${ok} 项可查证（${checks.filter((c) => c.ok).map((c) => c.label).join("',
)
r = r.replace('unknown: missing.length ? `缺少：${missing.join("、")}` : undefined,',
              'unknown: missing.length ? `还没确认：${missing.join("、")}` : undefined,')
r = r.replace('return { score: null, unknown: "活动类别未知，无法判断客群相关性" };',
              'return { score: null, unknown: "还不知道活动类别，暂时判断不了客群" };')
r = r.replace('return { score: null, unknown: "缺少已核验坐标，无法计算距离" };',
              'return { score: null, unknown: "场馆位置还没确认，暂时算不了距离" };')
ranking.write_text(r, encoding="utf-8")
print("  ranking 文案已改:", "关键信息有" in ranking.read_text(encoding="utf-8"))

# ---- 工作台卡片 ----
bench = root / "frontend" / "src" / "pages" / "Workbench" / "index.tsx"
s = bench.read_text(encoding="utf-8")

if "值得关注" not in s:
    anchor = "                  {unknown.length > 0 && ("
    block = '''                  {(() => {
                    // 主界面只说人话；分档规则放 tooltip，避免变成黑箱打分
                    const level = (value: number | null, high: number, mid: number) =>
                      value === null ? "不足" : value >= high ? "高" : value >= mid ? "中" : "低";
                    const worth = level(
                      byDimension.relevance === null || byDimension.timing === null
                        ? null
                        : (byDimension.relevance + byDimension.timing) / 2,
                      0.75,
                      0.5,
                    );
                    const reliable = level(byDimension.credibility, 0.75, 0.4);
                    return (
                      <small className="rank-plain">
                        值得关注：<strong>{worth}</strong> · 信息可靠：<strong>{reliable}</strong>
                        <Tooltip
                          title={
                            "值得关注 = 业务相关性与紧迫度的平均（≥0.75 高，≥0.5 中，其余低）；" +
                            "信息可靠 = 关键字段的证据覆盖率（≥0.75 高，≥0.4 中，其余低）。" +
                            "原始分数：" +
                            "相关性 " + fmtDim(byDimension.relevance) +
                            " · 距离 " + fmtDim(byDimension.distance) +
                            " · 可信度 " + fmtDim(byDimension.credibility) +
                            " · 紧迫度 " + fmtDim(byDimension.timing)
                          }
                        >
                          <span className="rank-help"> 怎么判断的</span>
                        </Tooltip>
                      </small>
                    );
                  })()}
'''
    s = s.replace(anchor, block + anchor, 1)

    # 维度分数那行改为默认不显示（信息已在 tooltip 里）
    s = s.replace('''                  <small className="rank-dims">
                    相关性 {fmtDim(byDimension.relevance)} · 距离 {fmtDim(byDimension.distance)} ·
                    可信度 {fmtDim(byDimension.credibility)} · 紧迫度 {fmtDim(byDimension.timing)}
                  </small>
''', '')

    if 'Tooltip' not in s.split("export default")[0]:
        s = s.replace('import { Button, Select, Space, Tag } from "antd";',
                      'import { Button, Select, Space, Tag, Tooltip } from "antd";', 1)

    bench.write_text(s, encoding="utf-8")

print("  卡片已改人话:", "值得关注" in bench.read_text(encoding="utf-8"))
