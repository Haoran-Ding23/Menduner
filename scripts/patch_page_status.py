"""页面区分官方商圈与候选集聚点（三段小改动）。"""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = p.read_text(encoding="utf-8")

block_old = """            <div>
              <strong>{coverage.areaVerified}</strong>
              <small>行政区一致</small>
            </div>"""
block_new = """            <div>
              <strong>{coverage.officialCount}</strong>
              <small>官方商圈</small>
            </div>
            <div>
              <strong>{coverage.candidateCount}</strong>
              <small>候选集聚点</small>
            </div>
            <div>
              <strong>{coverage.areaVerified}</strong>
              <small>行政区一致</small>
            </div>"""
if "officialCount" not in s:
    s = s.replace(block_old, block_new, 1)

options_old = """              options={areas.map((area) => ({
                value: area.id,
                label: area.name + "（" + (area.parentName ?? "父级未知") + "）",
              }))}"""
options_new = """              options={areas.map((area) => ({
                value: area.id,
                label:
                  (area.status === "candidate" ? "[候选] " : "") +
                  area.name +
                  "（" + (area.parentName ?? "父级未知") + "）",
              }))}"""
if "[候选] " not in s:
    s = s.replace(options_old, options_new, 1)

tag_old = """            {profile && profile.area.quality !== "verified" && ("""
tag_new = """            {profile?.area.status === "candidate" && <Tag>候选商业集聚点</Tag>}
            {profile && profile.area.quality !== "verified" && ("""
if "候选商业集聚点" not in s:
    s = s.replace(tag_old, tag_new, 1)

p.write_text(s, encoding="utf-8")
print("  officialCount:", "officialCount" in s)
print("  候选前缀:", "[候选] " in s)
print("  候选标识:", "候选商业集聚点" in s)
