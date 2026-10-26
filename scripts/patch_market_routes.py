"""给 main.py 加商圈聚合的三个只读路由（GPT Round 14 批准的数据层）。"""
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "backend" / "main.py"
text = target.read_text(encoding="utf-8")

if "/market/coverage" in text:
    print("  已存在，跳过")
    raise SystemExit

anchor = "    @app.get('/geo/tree')"
block = '''    @app.get('/market/coverage')
    def market_coverage(radius: int | None = None):
        """商圈数据能力：有多少商圈有中心点、多少活动能匹配上、多少保留歧义。

        商圈没有正式边界，这里的数字是「中心点周边估算范围」，接口里带 note 字段说明。
        """
        return market_area.coverage(path, _radius(radius))

    @app.get('/market/areas')
    def market_areas(radius: int | None = None):
        return {'areas': market_area.ranking(path, _radius(radius))}

    @app.get('/market/area/{area_id}')
    def market_area_profile(area_id: str, radius: int | None = None,
                            start: str | None = None, end: str | None = None):
        try:
            return market_area.profile(path, area_id, _radius(radius), start, end)
        except KeyError:
            raise HTTPException(status_code=404, detail='商圈不存在') from None

'''
text = text.replace(anchor, block + anchor, 1)

helper_anchor = "def _session_token(request: Request) -> str | None:"
helper = '''def _radius(value: int | None) -> int:
    """半径只接受合理区间，避免一次请求扫全城或传负数。"""
    if value is None:
        return market_area.DEFAULT_RADIUS
    return max(200, min(int(value), 5000))


'''
text = text.replace(helper_anchor, helper + helper_anchor, 1)

imports_anchor = "from backend import geo"
text = text.replace(imports_anchor, "from backend import market_area\n" + imports_anchor, 1)

target.write_text(text, encoding="utf-8")
print("  已加 /market/coverage、/market/areas、/market/area/{id} 与 _radius 帮助函数")
