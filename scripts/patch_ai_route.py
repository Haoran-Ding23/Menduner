"""加 AI 商圈分析路由，并在前端挂一张「AI 解读」卡片（证据约束型）。

后端只返回结构化 JSON；前端只负责渲染 findings / unknowns / limitations，
并明确标注这是 AI 生成、未经核实。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---- 后端路由 ----
main = root / "backend" / "main.py"
m = main.read_text(encoding="utf-8")
if "/ai/market-analysis/" not in m:
    anchor = "    @app.get('/graph/query/event/{event_id}')"
    block = '''    @app.get('/ai/market-analysis/{area_id}')
    def ai_market_analysis(area_id: str, radius: int | None = None,
                           start: str | None = None, end: str | None = None):
        """证据约束型 AI 商圈解读。

        只解释输入里已有的指标；模型编造的数字、白名单外的指标、经营预测措辞都会被丢弃。
        模型不可用时返回 available=false，绝不生成替代内容。
        """
        try:
            return ai_analysis.analyze_area(path, area_id, _radius(radius), start, end)
        except KeyError:
            raise HTTPException(status_code=404, detail='商圈不存在') from None

'''
    m = m.replace(anchor, block + anchor, 1)
    m = m.replace("from backend import graph_chain", "from backend import ai_analysis\nfrom backend import graph_chain", 1)
    main.write_text(m, encoding="utf-8")
print("  路由已加:", "/ai/market-analysis/" in main.read_text(encoding="utf-8"))

# ---- 前端类型与服务 ----
api = root / "frontend" / "src" / "services" / "api.ts"
a = api.read_text(encoding="utf-8")
if "loadAiMarketAnalysis" not in a:
    a = a.rstrip() + '''

// ---- AI 商圈解读（证据约束型）：前端只渲染，不重算 ----
export interface AiMarketAnalysis {
  available: boolean;
  reason: string | null;
  areaId: string;
  areaName: string;
  radiusMeters: number;
  verificationStatus: "ai_analysis_unverified";
  metrics: Record<string, number | null>;
  summary: string;
  findings: { claim: string; metricKeys: string[] }[];
  unknowns: string[];
  limitations: string[];
  businessQuestions: string[];
  rejected: { claim: string; reason: string }[];
}

export async function loadAiMarketAnalysis(
  areaId: string,
  params: { radius?: number; start?: string; end?: string } = {},
): Promise<AiMarketAnalysis> {
  const response = await fetch(
    "/api/ai/market-analysis/" + encodeURIComponent(areaId) + marketQuery(params),
  );
  if (!response.ok) throw new Error("AI 解读加载失败");
  return response.json();
}
'''
    api.write_text(a, encoding="utf-8")
print("  服务已加:", "loadAiMarketAnalysis" in api.read_text(encoding="utf-8"))
