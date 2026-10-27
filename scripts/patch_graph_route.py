"""给 main.py 加图谱链路路由：GET /graph/query/event/{event_id}（GPT Round 27 批准）。"""
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "backend" / "main.py"
text = target.read_text(encoding="utf-8")

if "/graph/query/event/" in text:
    print("  已存在，跳过")
    raise SystemExit

anchor = "    @app.get('/market/coverage')"
block = '''    @app.get('/graph/query/event/{event_id}')
    def graph_event_chain(event_id: str, radius: int | None = None):
        """活动 → 场馆 → 周边酒店/餐饮/交通 的可解释链路。

        每条边都带 kind(recorded/computed)、verificationStatus 与证据或计算参数；
        超出半径的中心点不建关系，只作为信息返回。
        """
        try:
            return graph_chain.event_chain(path, event_id, _radius(radius))
        except KeyError:
            raise HTTPException(status_code=404, detail='活动不存在') from None

'''
text = text.replace(anchor, block + anchor, 1)
text = text.replace("from backend import market_area", "from backend import graph_chain\nfrom backend import market_area", 1)
target.write_text(text, encoding="utf-8")
print("  已加 /graph/query/event/{event_id}")
