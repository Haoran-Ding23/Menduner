import { useState } from "react";
import { Alert, InputNumber, Space, Table, Tag } from "antd";
import { computeScenarios, formatMoney, type ScenarioInput } from "../../services/scenario";

/**
 * 情景面板：让用户自己填参数，然后看到低/中/高三档与完整计算过程。
 *
 * 刻意不做的事：不预填「看起来合理」的人数与消费额。预填会让一个假设冒充来源数据，
 * 而屏幕上第一个数字一旦出现，很少有人再回头核对它从哪来。
 */
export default function ScenarioPanel({ eventName }: { eventName: string }) {
  const [input, setInput] = useState<ScenarioInput>({
    attendance: null,
    spendPerVisitor: null,
    stayShare: null,
    roomRate: null,
    hotelShare: null,
  });
  const result = computeScenarios(input);

  const set = (key: keyof ScenarioInput) => (value: number | null) =>
    setInput((prev) => ({ ...prev, [key]: value }));

  const fields: { key: keyof ScenarioInput; label: string; hint: string; step?: number }[] = [
    { key: "attendance", label: "预计到场人次", hint: "系统没有采集该活动的到场人数" },
    { key: "spendPerVisitor", label: "人均商圈消费（元）", hint: "需自行估计" },
    { key: "stayShare", label: "需住宿比例（0-1）", hint: "到场人次中过夜的比例", step: 0.05 },
    { key: "roomRate", label: "平均房价（元/间夜）", hint: "本店或商圈均价" },
    { key: "hotelShare", label: "本店份额（0-1）", hint: "周边住宿中本店可占的比例", step: 0.05 },
  ];

  return (
    <div className="scenario-panel">
      <Alert
        type="info"
        showIcon
        message={`情景估算 · ${eventName}`}
        description="下面的金额由你填写的参数推算，属于情景假设，不是观测结果。每格都标了参数性质；参数留空时不会给出任何金额。"
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
              step={field.step ?? 1}
              style={{ width: "100%" }}
              value={input[field.key] ?? null}
              onChange={(value) => set(field.key)(typeof value === "number" ? value : null)}
              placeholder={field.hint}
            />
          </label>
        ))}
      </div>

      {!result.ok ? (
        <Alert
          className="gap-top"
          type="warning"
          showIcon
          message="缺少关键参数，暂不给出金额"
          description={`还需要：${result.missing.join("、")}。缺少时任何金额都会是编造的。`}
        />
      ) : (
        <>
          <Table
            className="gap-top"
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={result.scenarios}
            columns={[
              { title: "情景", dataIndex: "label", width: 90 },
              {
                title: "到场人次",
                dataIndex: "attendance",
                render: (value: number, row) => `${value.toLocaleString()}（×${row.factor}）`,
              },
              {
                title: "商圈整体消费",
                dataIndex: "districtSpend",
                render: (value: number) => formatMoney(value),
              },
              {
                title: "住宿支出总额",
                dataIndex: "lodgingSpend",
                render: (value: number) => formatMoney(value),
              },
              {
                title: "本店住宿收入",
                dataIndex: "hotelRevenue",
                render: (value: number) => <strong>{formatMoney(value)}</strong>,
              },
              { title: "本店间夜", dataIndex: "roomNights", render: (value: number) => value.toLocaleString() },
            ]}
          />
          <Space direction="vertical" size={4} className="gap-top scenario-formula">
            <small className="muted">计算过程</small>
            {result.formula.map((line) => (
              <small key={line} className="muted">· {line}</small>
            ))}
          </Space>
        </>
      )}

      <Alert className="gap-top" type="success" showIcon message="这一块不是净新增收益" description={result.note} />
    </div>
  );
}
