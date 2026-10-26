"""把「演示路径」页并入第一个动作页，PPT 收到 10 页（GPT Round 13 的保留清单）。"""
from pathlib import Path

target = Path(__file__).resolve().parent / "build_mentor_files.py"
text = target.read_text(encoding="utf-8")

start = text.find("    # 5 演示路径")
end = text.find("    # 6 动作一")
if start == -1 or end == -1:
    raise SystemExit("  未找到演示路径页标记")

removed = text[start:end]
text = text[:start] + text[end:]

text = text.replace(
    'slide = page("① 发现活动：地图与清单", "演示 1/3")',
    'slide = page("① 发现活动：地图与清单", "演示路径：发现活动 → 酒店跟进 → 导出简报（约 13 分钟）")',
)
target.write_text(text, encoding="utf-8")
print(f"  已删除演示路径页（{len(removed.splitlines())} 行），眉标改为三步提示")
