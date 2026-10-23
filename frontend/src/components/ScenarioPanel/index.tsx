import { useState } from "react";
import { Alert, Checkbox, InputNumber, Space, Table, Tag } from "antd";
import { computeScenarios, formatMoney, type ScenarioInput } from "../../services/scenario";

/**
 * 情景面板：让用户自己填参数，然后看到低/中/高三档与完整计算过程。
 *
 * 刻意不做的事：不预填「看起来合理」的人数与消费额。预填会让一个假设冒充来源数据，
 * 而屏幕上第一个数字一旦出现，很少有人再回头核对它从哪来。
 *
 * 参数分组顺序对应计算链：需求侧（访客、住宿比例、晚数、每间人数）→ 价格（市场房价、本店
 * 房价）→ 分配（本店份额）→ 消费（人均消费、是否含住宿）。顺序就是读者核对公式的顺序。
 */
export default function ScenarioPanel({ eventName }: { eventName: string }) {
  const [input, setInput] = useState<ScenarioInput>({
    visitors: null,
    stayShare: null,
    avgNights: null,
    guestsPerRoom: null,
    marketRate: null,
    hotelShare: null,
    hotelRate: null,
    spendPerVisitor: null,
    spendIncludesLodging: false,
  });
  const result = computeScenarios(input);

  const set = (key: keyof ScenarioInput) => (value: number | null) =>
    setInput((prev) => ({ ...prev, [key]: value }));

  const fields: {
    key: keyof ScenarioInput;
    label: string;
    hint: string;
    step?: number;
    max?: number;
  }[] = [
    { key: "visitors", label: "不重复访客人数", hint: "不是累计人次；一人多天只算 1 人" },
    { key: "stayShare", label: "住宿比例（0-1）", hint: "访客中需要在本地过夜的比例", step: 0.05, max: 1 },
    { key: "avgNights", label: "平均住宿晚数（晚）", hint: "住宿者平均住几晚", step: 0.5 },
    { key: "guestsPerRoom", label: "平均每间入住人数", hint: "常见值为 2；必须大于 0" },
    { key: "marketRate", label: "市场平均房价（元/间夜）", hint: "商圈口径", },
    { key: "hotelShare", label: "本店份额（0-1）", hint: "周边住宿中本店可占的比例", step: 0.05, max: 1 },
    { key: "hotelRate", label: "本店平均房价（可选）", hint: "留空表示与市场同价" },
    { key: "spendPerVisitor", label: "人均商圈消费（元/人）", hint: "需自行估计" },
  ];

  const errors = result.issues.filter((issue) => issue.level === "error");
  const warnings = result.issues.filter((issue) => issue.level === "warn");

  return (
    <div className="scenario-panel">
      <Alert
        type="info"
        showIcon
        message={`情景估算 · ${eventName}`}
        description="下面的金额由你填写的参数推算，属于参数情景，不是观测结果，也不是置信区间。每格都标了参数性质；参数留空时不会给出任何金额。"
      />

      <div className="scenario-inputs">
        {fields.map((field) => (
          <label key={field.key} className="scenario-field">
            <span className="scenario-label">
              {field.label}
              <Tag color="default">用户输入</Tag>
            </span>
            <InputNumber
              min={0}
              max={field.max}
              step={field.step ?? 1}
              style={{ width: "100%" }}
              value={(input[field.key] as number | null) ?? null}
              onChange={(value) => set(field.key)(typeof value === "number" ? value : null)}
              placeholder={field.hint}
              status={errors.some((issue) => issue.field === field.key) ? "error" : undefined}
            />
          </label>
        ))}
      </div>

      <Checkbox
        className="gap-top"
        checked={input.spendIncludesLodging ?? false}
        onChange={(change) =>
          setInput((prev) => ({ ...prev, spendIncludesLodging: change.target.checked }))
        }
      >
        商圈总消费已包含住宿支出（勾选后住宿支出不再重复相加，并检查两者是否矛盾）
      </Checkbox>

      {errors.length > 0 && (
        <Alert
          className="gap-top"
          type="warning"
          showIcon
          message="参数不合法，暂不给出金额"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {errors.map((issue) => (
                <li key={issue.field + issue.message}>{issue.message}</li>
              ))}
            </ul>
          }
        />
      )}

      {result.ok && (
        <>
          {warnings.length > 0 && (
            <Alert
              className="gap-top"
              type="warning"
              showIcon
              message="参数之间不一致（待修正）"
              description={warnings.map((issue) => issue.message).join("；")}
            />
          )}
          <Table
            className="gap-top"
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={result.scenarios}
            columns={[
              { title: "情景", dataIndex: "label", width: 90 },
              {
                title: "访客人数",
                dataIndex: "visitors",
                render: (value: number, row) => `${value.toLocaleString()}（×${row.factor}）`,
              },
              { title: "市场间夜", dataIndex: "marketRoomNights", render: (v: number) => v.toLocaleString() },
              {
                title: "市场住宿支出",
                dataIndex: "marketLodgingSpend",
                render: (value: number) => formatMoney(value),
              },
              { title: "本店间夜", dataIndex: "hotelRoomNights", render: (v: number) => v.toLocaleString() },
              {
                title: "本店住宿收入",
                dataIndex: "hotelRevenue",
                render: (value: number) => <strong>{formatMoney(value)}</strong>,
              },
              {
                title: "商圈整体消费",
                dataIndex: "districtSpend",
                render: (value: number) => formatMoney(value),
              },
            ]}
          />
          <Space direction="vertical" size={4} className="gap-top scenario-formula">
            <small className="muted">计算过程</small>
            {result.formula.map((line) => (
              <small key={line} className="muted">
                · {line}
              </small>
            ))}
          </Space>
        </>
      )}

      <Alert className="gap-top" type="success" showIcon message="这一块不是净新增收益" description={result.note} />
    </div>
  );
}
