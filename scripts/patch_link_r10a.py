"""12 轮第 10 轮：图谱 → 审核台（带字段定位）。

链路：图谱摘要里「在哪举办 / 信息来自」旁加「核对这条」，
跳到 /evidence?event=<id>&field=<字段>；审核台读取 field 参数，
滚动到该字段行并高亮，让审核员立刻看到该核对哪儿。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---------- 1) 摘要组件：加核对入口 ----------
summary = root / "frontend" / "src" / "components" / "GraphRelationSummary" / "index.tsx"
s = summary.read_text(encoding="utf-8")

s = s.replace("""  onOpenGraph?: () => void;
}) {""",
"""  onOpenGraph?: () => void;
  /** 跳到审核台核对某个字段（venueName / sourceUrl） */
  onVerify?: (field: string) => void;
}) {""", 1)
s = s.replace("  eventId,\n  onOpenGraph,\n}: {", "  eventId,\n  onOpenGraph,\n  onVerify,\n}: {", 1)

s = s.replace("""        <span className="relation-value">
          {venueNode?.name ?? "未关联场馆"}""",
"""        <span className="relation-value">
          {venueNode?.name ?? "未关联场馆"}""", 1)

# 在哪举办 行尾加核对
s = s.replace("""          ) : null}
        </span>
      </div>
      <div className="relation-line">
        <span className="relation-key">信息来自</span>""",
"""          ) : null}
          {onVerify && (
            <Button size="small" type="link" style={{ padding: "0 6px" }} onClick={() => onVerify("venueName")}>
              核对场地
            </Button>
          )}
        </span>
      </div>
      <div className="relation-line">
        <span className="relation-key">信息来自</span>""", 1)

# 信息来自 行尾加核对
s = s.replace("""              {" "}
              查看原始记录
            </a>
          )}
        </span>
      </div>""",
"""              {" "}
              查看原始记录
            </a>
          )}
          {onVerify && (
            <Button size="small" type="link" style={{ padding: "0 6px" }} onClick={() => onVerify("sourceUrl")}>
              核对来源
            </Button>
          )}
        </span>
      </div>""", 1)

summary.write_text(s, encoding="utf-8")
print("  摘要核对入口:", "核对场地" in summary.read_text(encoding="utf-8"))

# ---------- 2) 图谱页：接线 ----------
page = root / "frontend" / "src" / "pages" / "KnowledgeGraph" / "index.tsx"
p = page.read_text(encoding="utf-8")
if "onVerify" not in p:
    p = p.replace("<GraphRelationSummary eventId={id} onOpenGraph={() => setShowCanvas(true)} />",
                  '<GraphRelationSummary\n'
                  '          eventId={id}\n'
                  '          onOpenGraph={() => setShowCanvas(true)}\n'
                  '          onVerify={(field) => go("/evidence", id, { field })}\n'
                  '        />', 1)
    page.write_text(p, encoding="utf-8")
print("  图谱页接线:", 'go("/evidence", id, { field })' in page.read_text(encoding="utf-8"))
