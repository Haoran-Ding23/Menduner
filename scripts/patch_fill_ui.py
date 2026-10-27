"""审核台缺失字段加「补录」按钮与弹窗。"""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = p.read_text(encoding="utf-8")

# 1) 引入 Modal 与 fillEvidence
s = s.replace('import { Alert, App, Button, Input, Select, Space, Switch, Table, Tag, Tooltip, message as staticMessage } from "antd";',
              'import { Alert, App, Button, Input, Modal, Select, Space, Switch, Table, Tag, Tooltip, message as staticMessage } from "antd";', 1)
if "fillEvidence" not in s:
    s = s.replace('import { useIdentity, canReview } from "../../hooks/useIdentity";',
                  'import { fillEvidence } from "../../services/api";\nimport { useIdentity, canReview } from "../../hooks/useIdentity";', 1)

# 2) 状态
if "fillTarget" not in s:
    s = s.replace("  const [simpleOnly, setSimpleOnly] = useState(true);",
"""  const [simpleOnly, setSimpleOnly] = useState(true);
  // 人工补录：缺失字段没有可核对记录，只能补录（必须带来源）
  const [fillTarget, setFillTarget] = useState<Evidence | null>(null);
  const [fillValue, setFillValue] = useState("");
  const [fillSource, setFillSource] = useState("");
  const [fillNote, setFillNote] = useState("");
  const [fillBusy, setFillBusy] = useState(false);""", 1)

# 3) 缺失行改为「补录」按钮
s = s.replace('''                    if (missing) {
                      return <span className="muted">缺失，无需核对</span>;
                    }''',
'''                    if (missing) {
                      return (
                        <Button
                          size="small"
                          disabled={!reviewer}
                          onClick={() => {
                            setFillTarget(e);
                            setFillValue("");
                            setFillSource(e.sourceUrl ?? "");
                            setFillNote("");
                          }}
                        >
                          补录
                        </Button>
                      );
                    }''', 1)

# 4) 弹窗（放在最外层 fragment 结束前）
if "补录这个字段" not in s:
    anchor = "    </>"
    idx = s.rfind(anchor)
    modal = '''
      <Modal
        title="补录这个字段"
        open={Boolean(fillTarget)}
        onCancel={() => setFillTarget(null)}
        okText="保存补录"
        confirmLoading={fillBusy}
        onOk={async () => {
          if (!fillTarget) return;
          if (!fillSource.trim()) {
            message.warning("必须填写来源链接：没有来源的信息不写入");
            return;
          }
          setFillBusy(true);
          try {
            const result = await fillEvidence({
              eventId: fillTarget.entityId,
              field: fillTarget.field,
              value: fillValue,
              sourceUrl: fillSource,
              reviewer: String(identity.login ?? "reviewer"),
              note: fillNote || undefined,
            });
            message.success("已补录：" + (result.fieldLabel ?? fillTarget.field));
            setFillTarget(null);
            await reloadData();
          } catch (error) {
            message.error((error as Error).message);
          } finally {
            setFillBusy(false);
          }
        }}
      >
        <p className="muted" style={{ marginTop: 0 }}>
          补录会写成一条「人工补录」证据（状态已核验），并记录补录人与时间；必须填来源链接。
        </p>
        <p>
          <strong>字段：</strong>
          {FIELD_LABELS[fillTarget?.field ?? ""] ?? fillTarget?.field}
        </p>
        <p style={{ marginBottom: 6 }}>
          <strong>值</strong>
        </p>
        <Input
          aria-label="补录值"
          placeholder="例如：苏州文化艺术中心大剧院"
          value={fillValue}
          onChange={(event) => setFillValue(event.target.value)}
        />
        <p style={{ margin: "12px 0 6px" }}>
          <strong>来源链接</strong>（必填）
        </p>
        <Input
          aria-label="补录来源链接"
          placeholder="https://..."
          value={fillSource}
          onChange={(event) => setFillSource(event.target.value)}
        />
        <p style={{ margin: "12px 0 6px" }}>
          <strong>备注</strong>（可选）
        </p>
        <Input
          aria-label="补录备注"
          placeholder="例如：来自官方公告第二段"
          value={fillNote}
          onChange={(event) => setFillNote(event.target.value)}
        />
      </Modal>
'''
    s = s[:idx] + modal + s[idx:]

p.write_text(s, encoding="utf-8")
t = p.read_text(encoding="utf-8")
print("  Modal:", "补录这个字段" in t)
print("  fillEvidence 调用:", "fillEvidence({" in t)
print("  状态:", "fillTarget" in t)
