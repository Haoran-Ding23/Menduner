"""加人工补录路由 + 前端服务与弹窗。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

main = root / "backend" / "main.py"
m = main.read_text(encoding="utf-8")
if "/review/fill" not in m:
    anchor = "    @app.get('/review/{event_id}')"
    block = '''    @app.post('/review/fill')
    def review_fill(body: FillRequest, principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """人工补录缺失字段：必须带来源链接，留痕补录人，方法标记为 manual_entry。"""
        try:
            return manual_fill.fill(
                path,
                event_id=body.event_id,
                field=body.field,
                value=body.value,
                source_url=body.source_url,
                reviewer=body.reviewer,
                note=body.note,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail='活动不存在') from None
        except manual_fill.FillError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

'''
    m = m.replace(anchor, block + anchor, 1)
    m = m.replace("from backend import manual_fill", "from backend import manual_fill", 1)
    if "from backend import manual_fill" not in m:
        m = m.replace("from backend import ai_analysis", "from backend import ai_analysis\nfrom backend import manual_fill", 1)
    m = m.replace("class AiReviewLabel(BaseModel):",
                  '''class FillRequest(BaseModel):
    """人工补录一个缺失字段。"""
    event_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=4, max_length=500)
    reviewer: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=300)


class AiReviewLabel(BaseModel):''', 1)
    main.write_text(m, encoding="utf-8")
print("  路由已加:", "/review/fill" in main.read_text(encoding="utf-8"))

api = root / "frontend" / "src" / "services" / "api.ts"
a = api.read_text(encoding="utf-8")
if "fillEvidence" not in a:
    a = a.rstrip() + '''

// ---- 人工补录缺失字段（必须带来源；留痕补录人）----
export async function fillEvidence(input: {
  eventId: string;
  field: string;
  value: string;
  sourceUrl: string;
  reviewer: string;
  note?: string;
}): Promise<{ ok: boolean; action: string; fieldLabel: string }> {
  const response = await fetch("/api/review/fill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_id: input.eventId,
      field: input.field,
      value: input.value,
      source_url: input.sourceUrl,
      reviewer: input.reviewer,
      note: input.note ?? null,
    }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: "" }));
    throw new Error(detail.detail || "补录失败（需要审核角色）");
  }
  return response.json();
}
'''
    api.write_text(a, encoding="utf-8")
print("  前端服务已加:", "fillEvidence" in api.read_text(encoding="utf-8"))
