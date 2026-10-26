"""按 GPT Round 13 的审阅意见修改生成脚本。

1. PPT 从 15 页压到 10 页（删第 2/5/9/10/13 页，要点并入相邻页）
2. 改写第 4 页「每日快照 3 份可看新增改期消失」这句最容易被反驳的话
3. Word 里改三个问题：Q3 换成「哪个环节最耗时」、Q8 先问行业通用方法、Q10 挪到试点之后
4. 被删的第 9 页（六个功能页说明）改为 Word 附录，不丢内容
"""
from pathlib import Path

target = Path(__file__).resolve().parent / "build_mentor_files.py"
lines = target.read_text(encoding="utf-8").splitlines(True)


def block(start_no, end_no):
    """按 1-based 行号取 [start, end) 的代码块。"""
    return "".join(lines[start_no - 1:end_no - 1])


cover = block(151, 160)
position = block(169, 186)
data = block(186, 196)
demo_path = block(196, 209)
acts = block(209, 237)        # 第 6、7、8 页
asks_values = block(258, 278)  # 第 11、12 页
closing = block(294, 303)      # 第 14 页
thanks = block(303, len(lines) + 1)  # 第 15 页

new_cover = cover.replace(
    '    text(slide, "在线版本：entgroup14.com", 0.95, 5.65, 11, 0.4, 13, color=MUTED)',
    '    text(slide, "在线版本：entgroup14.com", 0.95, 5.35, 11, 0.4, 13, color=MUTED)\n'
    '    text(slide, "今天 30% 汇报、40% 听您讲、30% 争取一次小范围验证；我们不是来谈采购的。",\n'
    '         0.95, 6.1, 11.3, 0.45, 15, color=MUTED)',
)

new_position = position.replace(
    '    text(slide, "数据为 2026-10-26 生产环境实测；太仓市直接归属活动 16 条 —— 这是样本，不是全覆盖。",\n'
    '         0.95, 5.9, 11.3, 0.4, 13, color=MUTED)',
    '    text(slide, "数据为 2026-10-26 生产环境实测；太仓市直接归属活动 16 条 —— 这是样本，不是全覆盖。",\n'
    '         0.95, 5.58, 11.3, 0.4, 13, color=MUTED)\n'
    '    text(slide, "明确不做：需求预测与房价建议 · 替代酒店 RMS · 承诺 RevPAR/ADR · 把参数情景说成真实收入",\n'
    '         0.95, 6.16, 11.3, 0.4, 14, color=ACCENT)',
)

old_row = (
    '[f"每日快照（当前 {FACTS[\'快照\']} 份），同一天的数据可比", "能看到活动是新增、改期还是消失"],'
)
new_row = (
    '[f"已积累 {FACTS[\'快照\']} 份历史快照，可比较对应时间区间内观察到的信息变化",\n'
    '         "未再次采集到的活动标「待核验」，不直接判定为取消"],'
)
new_data = data.replace(old_row, new_row)

head = "".join(lines[:150])
tail = "".join(lines[len(lines):])

rebuilt = "".join(
    [new_cover, new_position, new_data, demo_path, acts, asks_values, closing, thanks]
)
target.write_text(head + rebuilt + tail, encoding="utf-8")
print("  PPT 已重排")

# ---- Word：改三个问题 + 加附录表 ----
text = target.read_text(encoding="utf-8")

q3_old = '["3", "有没有出现过活动信息发现太晚，导致错过营销或经营准备的情况？", "真实业务痛点"],'
q3_new = '["3", "目前活动信息获取的过程中，哪个环节最耗费时间？", "真实业务痛点（不质疑对方工作）"],'
text = text.replace(q3_old, q3_new)

q8_old = '["8", "酒店是否会评估大型活动对入住率、ADR 或 RevPAR 的影响？通常如何评估？", "经济分析的现实基础"],'
q8_new = '["8", "行业里通常怎么评估大型活动对入住的影响？贵店会参考哪些指标？", "经济分析的现实基础（先问通用方法，不打听敏感数据）"],'
text = text.replace(q8_old, q8_new)

q10_old = '["10", "如果试点有效，企业内部通常还需要经过哪些环节才能正式采用？", "采购、合规、预算流程"],'
q10_new = '["10", "（试点有反馈之后再问）企业内部正式采用一般要经过哪些环节？", "采购、合规、预算流程（首访不问，避免显得功利）"],'
text = text.replace(q10_old, q10_new)

note_old = '    body("顺序原则：先请教实际工作 → 再谈产品价值 → 最后自然过渡到试点。", size=9.5,\n         color=RGBColor(0x6B, 0x72, 0x80))'
note_new = ('    body("顺序原则：先请教实际工作 → 再谈产品价值 → 最后自然过渡到试点。"\n'
            '         "第一次见面建议只问 1、2、4、5、6 五题；第 8 题先问行业通用方法，第 10 题留到试点有反馈之后再问。",\n'
            '         size=9.5, color=RGBColor(0x6B, 0x72, 0x80))')
text = text.replace(note_old, note_new)

appendix_old = '    heading("七、明确不做的四件事", 1)'
appendix_new = ('    heading("七、六个功能页面说明（老师追问时使用）", 1)\n'
                '    table(["页面", "回答什么问题"], [\n'
                '        ["知识图谱", "一个活动和哪些场馆、地区、酒店有关；缺的关系写「待补充」"],\n'
                '        ["商圈洞察", "行政区与商业商圈分开统计；经济情景是参数假设，缺参数不出金额"],\n'
                '        ["酒店活动情报", "某家酒店周边 10 km 内的活动；坐标未核验的不计入距离"],\n'
                '        ["找酒店", "按星级、地区、名称找已收录的 19 家酒店"],\n'
                '        ["本店经营数据", "酒店自己上传经营数据，只在本店账号内可见"],\n'
                '        ["数据质量与来源", "每条数据能不能用、来源在哪、还缺什么"],\n'
                '    ], widths=[3.4, 12.4])\n\n'
                '    heading("八、明确不做的四件事", 1)')
text = text.replace(appendix_old, appendix_new)

target.write_text(text, encoding="utf-8")
print("  Word 已改三个问题并新增附录表")
