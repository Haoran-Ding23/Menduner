"""缺失字段单独成块，提供补录入口。

问题：补录入口在字段表行内，但默认视图只显示三项关键字段，
而缺失的多是辅助字段（主办方/结束日期/参与人数/赞助方），被过滤掉后根本看不到补录按钮。
方案：在三项摘要下方单独列出「缺失字段（可补录）」区块，不依赖表格过滤。
"""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = p.read_text(encoding="utf-8")

if "missingFields" not in s:
    s = s.replace("  const effectiveSimple = simpleOnly && pendingKeyCount > 0;",
"""  const effectiveSimple = simpleOnly && pendingKeyCount > 0;
  // 缺失字段（没有可核对记录）单独列出：它们多为辅助字段，默认三项视图会把它们过滤掉
  const isMissingField = (item: Evidence) =>
    item.value === null || item.value === undefined || item.value === "" || effectiveStatus(item) === "Missing";
  const missingFields = pendingFields.filter(isMissingField);""", 1)

    # 在关键三项摘要之后插入缺失字段区块
    s = s.replace('''              <p className="dq-group-title">''',
'''              {missingFields.length > 0 && (
                <div className="missing-block">
                  <strong>缺失字段（{missingFields.length} 个，可补录）</strong>
                  <div className="missing-items">
                    {missingFields.map((item) => (
                      <span key={item.id} className="missing-item">
                        {FIELD_LABELS[item.field] ?? item.field}
                        <Button
                          size="small"
                          type="link"
                          style={{ padding: "0 4px" }}
                          disabled={!reviewer}
                          onClick={() => {
                            setFillTarget(item);
                            setFillValue("");
                            setFillSource(item.sourceUrl ?? "");
                            setFillNote("");
                          }}
                        >
                          补录
                        </Button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <p className="dq-group-title">''', 1)

p.write_text(s, encoding="utf-8")
print("  缺失区块:", "missing-block" in p.read_text(encoding="utf-8"))
