"""便民化第 2 轮（P0-4）：商圈洞察术语换成非专业用户能懂的说法。

GPT Round 25 给的映射（主界面说人话，第二层准确说明保留）：
  唯一近邻 → 只靠近一处（活动只进入一个中心点的范围）
  保留歧义 → 靠近多处（同时进入多个中心范围，未强行分配）
  未匹配   → 暂未匹配（不在任何中心范围内，不代表当地没有活动）
  可归属   → 已匹配活动（基于场馆坐标与距离规则，不等于正式商圈归属）
  空间匹配率 → 已匹配比例
  候选集聚点 → 商业参考点（POI 聚类得到，非官方认定商圈）
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = page.read_text(encoding="utf-8")

pairs = [
    ('label: "分析中心"', 'label: "分析地点"'),
    ('label: "唯一近邻"', 'label: "只靠近一处"'),
    ('label: "保留歧义"', 'label: "靠近多处"'),
    ('label: "未匹配"', 'label: "暂未匹配"'),
    ('<small>唯一近邻</small>', '<small>只靠近一处</small>'),
    ('<small>保留歧义</small>', '<small>靠近多处</small>'),
    ('<small>未匹配</small>', '<small>暂未匹配</small>'),
    ('<small>窗口内可归属活动</small>', '<small>本月能对上的活动</small>'),
    ('<small>窗口内保留歧义</small>', '<small>靠近多处（待定）</small>'),
    ('<small>全年可归属</small>', '<small>全年能对上</small>'),
    ('<small>空间匹配率</small>', '<small>已匹配比例</small>'),
    ("<small>保留歧义</small>", "<small>靠近多处</small>"),
    ('<h3>活动归属构成</h3>', '<h3>活动能不能对上地点</h3>'),
    ('<h3>中心点近邻活动 Top 10</h3>', '<h3>活动最多的十个地点</h3>'),
    ('<h3>半径敏感性</h3>', '<h3>换个范围会怎样</h3>'),
    ('<h3>周度活动趋势</h3>', '<h3>每周有多少活动</h3>'),
    ('<h3>活动类别构成</h3>', '<h3>活动都有哪些类型</h3>'),
    ('<h3>周边已收录住宿设施</h3>', '<h3>周边收录的住宿</h3>'),
    ('<Tag>候选商业集聚点</Tag>', '<Tag>商业参考点（非官方商圈）</Tag>'),
    ('蓝=官方商圈 · 青=候选集聚点 · 点击切换画像', '蓝=官方商圈 · 青=参考地点 · 点击切换'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new)

# 顶部加一句"怎么算的"，保留准确口径
if "怎么算的" not in s:
    s = s.replace(
        '        <p className="insight-sub">',
        '        <p className="insight-sub">\n'
        '          <Tooltip\n'
        '            title={\n'
        '              "只靠近一处＝活动只进入一个地点的范围；靠近多处＝同时进入多个地点范围，未强行分配；" +\n'
        '              "暂未匹配＝不在任何地点范围内，不代表当地没有活动；" +\n'
        '              "已匹配比例＝能对上地点的活动数 ÷ 有坐标的活动数。" +\n'
        '              "所有距离都是场馆坐标到地点中心点的直线距离。"\n'
        '            }\n'
        '          >\n'
        '            <span className="insight-help">怎么算的</span>\n'
        '          </Tooltip>\n',
        1,
    )

if 'Tooltip' not in s.split("export default")[0]:
    s = s.replace('import { Button, Collapse, Select, Space, Table, Tag } from "antd";',
                  'import { Button, Collapse, Select, Space, Table, Tag, Tooltip } from "antd";', 1)

page.write_text(s, encoding="utf-8")
print("  术语已换:", "只靠近一处" in page.read_text(encoding="utf-8"))
print("  帮助入口:", "怎么算的" in page.read_text(encoding="utf-8"))
