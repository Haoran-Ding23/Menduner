"""加 AI 建议核对的路由与前端服务。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

main = root / "backend" / "main.py"
m = main.read_text(encoding="utf-8")
if "/ai/review/trials" not in m:
    anchor = "    @app.get('/ai/market-analysis/{area_id}')"
    block = '''    @app.post('/ai/review/generate')
    def ai_review_generate(limit: int = 25, principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """生成 AI 审核建议（只写建议表，不改任何核验状态）。"""
        return ai_review.generate(path, max(1, min(limit, 60)))

    @app.get('/ai/review/trials')
    def ai_review_trials(batch: str | None = None, limit: int = 200):
        return ai_review.list_trials(path, batch, max(1, min(limit, 500)))

    @app.get('/ai/review/stats')
    def ai_review_stats():
        return ai_review.stats(path)

    @app.post('/ai/review/trials/{trial_id}/label')
    def ai_review_label(trial_id: str, body: AiReviewLabel,
                        principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """人工判定 AI 建议对/错并留痕（判定人 + 时间 + 备注）。"""
        try:
            return ai_review.label_trial(path, trial_id, body.verdict, principal, body.note)
        except KeyError:
            raise HTTPException(status_code=404, detail='建议不存在') from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

'''
    m = m.replace(anchor, block + anchor, 1)
    m = m.replace("from backend import ai_analysis", "from backend import ai_analysis\nfrom backend import ai_review", 1)
    # 请求体模型
    m = m.replace("class ReviewRequest(BaseModel):",
                  'class AiReviewLabel(BaseModel):\n    verdict: str = Field(pattern="^(agree|disagree)$")\n    note: str | None = Field(default=None, max_length=300)\n\n\nclass ReviewRequest(BaseModel):', 1)
    main.write_text(m, encoding="utf-8")
print("  路由已加:", "/ai/review/trials" in main.read_text(encoding="utf-8"))

api = root / "frontend" / "src" / "services" / "api.ts"
a = api.read_text(encoding="utf-8")
if "loadAiReviewTrials" not in a:
    a = a.rstrip() + '''

// ---- AI 审核建议（只建议，不改核验状态；人工判定留痕）----
export interface AiReviewTrial {
  id: string;
  event_id: string;
  field: string;
  current_value: string | null;
  suggested_value: string | null;
  confidence: string | null;
  reason: string | null;
  evidence: string | null;
  model: string | null;
  batch: string | null;
  created_at: string | null;
  verdict: "agree" | "disagree" | null;
  labeled_by: string | null;
  labeled_at: string | null;
  note: string | null;
}

export interface AiReviewStats {
  total: number;
  labeled: number;
  agree: number;
  disagree: number;
  errorRate: number | null;
  byField: { field: string; total: number; agree: number; disagree: number }[];
  note: string;
}

export async function loadAiReviewTrials(batch?: string): Promise<{ trials: AiReviewTrial[]; batches: string[] }> {
  const suffix = batch ? "?batch=" + encodeURIComponent(batch) : "";
  const response = await fetch("/api/ai/review/trials" + suffix, { cache: "no-store" });
  if (!response.ok) throw new Error("AI 建议加载失败");
  return response.json();
}

export async function loadAiReviewStats(): Promise<AiReviewStats> {
  const response = await fetch("/api/ai/review/stats", { cache: "no-store" });
  if (!response.ok) throw new Error("统计加载失败");
  return response.json();
}

export async function generateAiReview(limit = 25): Promise<{ batch: string; available: boolean; reason: string | null; created: number; rejected: { reason: string }[] }> {
  const response = await fetch("/api/ai/review/generate?limit=" + limit, { method: "POST" });
  if (!response.ok) throw new Error("生成失败（需要审核角色）");
  return response.json();
}

export async function labelAiReview(id: string, verdict: "agree" | "disagree", note?: string) {
  const response = await fetch("/api/ai/review/trials/" + encodeURIComponent(id) + "/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verdict, note: note ?? null }),
  });
  if (!response.ok) throw new Error("标注失败（需要审核角色）");
  return response.json();
}
'''
    api.write_text(a, encoding="utf-8")
print("  前端服务已加:", "loadAiReviewTrials" in api.read_text(encoding="utf-8"))
