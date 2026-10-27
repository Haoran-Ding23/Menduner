"""按行精确替换工作台卡片：去掉维度分数行，改为「值得关注 / 信息可靠」两句话 + tooltip。"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Workbench" / "index.tsx"
lines = page.read_text(encoding="utf-8").splitlines(True)

start = next(i for i, line in enumerate(lines) if 'className="rank-dims"' in line)
end = next(i for i, line in enumerate(lines) if 'rank-unknown' in line)

new_block = '''                  {(() => {
                    // 主界面只说人话；分档规则与原始分数放 tooltip，避免变成黑箱打分
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
                            "信息可靠 = 关键字段的证据覆盖率（≥0.75 高，≥0.4 中，其余低）。原始分数：" +
                            "相关性 " + fmtDim(byDimension.relevance) +
                            " · 距离 " + fmtDim(byDimension.distance) +
                            " · 可信度 " + fmtDim(byDimension.credibility) +
                            " · 紧迫度 " + fmtDim(byDimension.timing)
                          }
                        >
                          <span className="rank-help">怎么判断的</span>
                        </Tooltip>
                      </small>
                    );
                  })()}
'''

lines[start:end] = [new_block]
page.write_text("".join(lines), encoding="utf-8")

text = page.read_text(encoding="utf-8")
if "Tooltip" not in text.split("export default")[0]:
    text = text.replace('import { Button, Select, Space, Tag } from "antd";',
                        'import { Button, Select, Space, Tag, Tooltip } from "antd";', 1)
    page.write_text(text, encoding="utf-8")

print("  rank-plain 已插入:", "rank-plain" in page.read_text(encoding="utf-8"))
print("  rank-dims 已移除:", "rank-dims" not in page.read_text(encoding="utf-8"))
