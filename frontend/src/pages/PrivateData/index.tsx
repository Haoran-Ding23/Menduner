import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Select, Space, Table, Tag, message } from "antd";
import {
  PRIVATE_METRIC_LABELS,
  PRIVATE_METRIC_UNITS,
  importSpreadsheet,
  loadPrivateMetrics,
  type ImportPreview,
  type PrivateMetric,
  type PrivateRow,
  type PrivateSummary,
} from "../../services/privateData";

/**
 * A hotel's own numbers, and the way it gets them in.
 *
 * The upload is deliberately two steps: the file is parsed and shown - which column became
 * which metric, how many rows will be stored, and every row that could not be read with the
 * reason - and nothing is written until the customer presses the second button. A silently
 * applied wrong mapping would put occupancy figures in the price column and would only be
 * noticed when the numbers looked odd, which is far worse than asking once.
 *
 * Nothing on this page is shared with any other hotel: the backend resolves the hotel from the
 * session and reads its own database file.
 */
export default function PrivateData() {
  const [data, setData] = useState<PrivateSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await loadPrivateMetrics());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const readFile = async (picked: File) => {
    setFile(picked);
    setPreview(null);
    setBusy(true);
    setError("");
    try {
      const result = await importSpreadsheet(picked, { apply: false });
      setPreview(result);
      setMapping(result.mapping);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "解析失败");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const result = await importSpreadsheet(file, { apply: true, mapping });
      setPreview(result);
      message.success(`已写入 ${result.written ?? 0} 条`);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  // Columns the file actually has, so the customer can move a metric to a different column when
  // the automatic guess was wrong after seeing what it chose.
  const headerOptions = useMemo(
    () => (preview?.headers ?? []).map((h) => ({ label: h || "(空)", value: h })),
    [preview],
  );

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">私有数据</div>
        <h1>本店经营数据</h1>
        <p>
          上传本店的入住率、房价、间夜、渠道与房型数据。这些数据只在本店账号下可见，
          不与其他酒店共享，也不进入公开活动数据。
        </p>
      </div>

      {error && (
        <Alert
          className="gap-bottom"
          type="warning"
          showIcon
          message={error}
          description={
            error.includes("登录")
              ? "请先在右上角登录后再上传。"
              : error.includes("归属")
                ? "该账号还没有绑定酒店，请联系我们开通。"
                : undefined
          }
        />
      )}

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>上传表格</h3>
          <small className="muted">支持 Excel（.xlsx）与 CSV</small>
        </div>
        <Space wrap>
          <input
            type="file"
            accept=".csv,.xlsx,.xlsm"
            aria-label="选择表格文件"
            onChange={(e) => {
              const picked = e.target.files?.[0];
              if (picked) void readFile(picked);
            }}
          />
          {busy && <span className="muted">处理中…</span>}
        </Space>

        {preview && (
          <>
            <h4 style={{ marginTop: 18 }}>识别结果</h4>
            <p className="muted" style={{ marginTop: 0 }}>
              共读取 {preview.rowsRead} 行，可导入 {preview.acceptedCount} 条。
              如果某一列对错了，可以在下面改。
            </p>
            <Space wrap>
              {preview.metrics.map((metric) => (
                <label key={metric} className="mapping-row">
                  <span>{PRIVATE_METRIC_LABELS[metric as PrivateMetric] ?? metric}</span>
                  <Select
                    size="small"
                    style={{ width: 150 }}
                    aria-label={`${metric} 对应列`}
                    value={mapping[metric]}
                    options={headerOptions}
                    onChange={(value) =>
                      setMapping((prev) => ({ ...prev, [metric]: value }))
                    }
                  />
                </label>
              ))}
            </Space>

            {preview.issues.length > 0 && (
              <Alert
                className="gap-top"
                type="warning"
                showIcon
                message={`${preview.issues.length} 处无法导入，其余正常`}
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.issues.slice(0, 12).map((issue, i) => (
                      <li key={`${issue.row}-${i}`}>
                        第 {issue.row} 行：{issue.reason}
                      </li>
                    ))}
                    {preview.issues.length > 12 && (
                      <li>…另有 {preview.issues.length - 12} 处</li>
                    )}
                  </ul>
                }
              />
            )}

            {preview.sample.length > 0 && (
              <Table
                className="gap-top"
                size="small"
                rowKey={(row) => `${row.metric}-${row.period_start}-${row.value}`}
                dataSource={preview.sample}
                pagination={false}
                columns={[
                  {
                    title: "指标",
                    render: (_, row) =>
                      PRIVATE_METRIC_LABELS[row.metric as PrivateMetric] ?? row.metric,
                  },
                  { title: "周期", dataIndex: "period_start" },
                  {
                    title: "数值",
                    render: (_, row) =>
                      `${row.value}${PRIVATE_METRIC_UNITS[row.metric as PrivateMetric] ?? ""}`,
                  },
                  { title: "渠道", dataIndex: "channel", render: (v) => v ?? "—" },
                  { title: "房型", dataIndex: "room_type", render: (v) => v ?? "—" },
                ]}
              />
            )}

            <Space className="gap-top">
              <Button type="primary" loading={busy} onClick={() => void confirm()}>
                确认导入 {preview.acceptedCount} 条
              </Button>
              <Button onClick={() => setPreview(null)}>取消</Button>
            </Space>
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>已上传的数据</h3>
          <Space>
            <Tag>{data?.count ?? 0} 条</Tag>
            <Button size="small" onClick={() => void refresh()} loading={loading}>
              刷新
            </Button>
          </Space>
        </div>
        {data && data.rows.length > 0 ? (
          <Table<PrivateRow>
            size="small"
            rowKey="id"
            dataSource={data.rows}
            pagination={{ pageSize: 12 }}
            columns={[
              {
                title: "指标",
                width: 120,
                render: (_, row) =>
                  PRIVATE_METRIC_LABELS[row.metric as PrivateMetric] ?? row.metric,
              },
              { title: "周期起", dataIndex: "period_start", width: 120 },
              { title: "周期止", dataIndex: "period_end", width: 120,
                render: (v) => v ?? "—" },
              {
                title: "数值",
                width: 110,
                render: (_, row) =>
                  `${row.value}${PRIVATE_METRIC_UNITS[row.metric as PrivateMetric] ?? ""}`,
              },
              { title: "渠道", dataIndex: "channel", render: (v) => v ?? "—" },
              { title: "房型", dataIndex: "room_type", render: (v) => v ?? "—" },
              { title: "上传人", dataIndex: "uploaded_by", width: 110 },
              { title: "来源文件", dataIndex: "source_file", render: (v) => v ?? "—" },
            ]}
          />
        ) : (
          <Empty
            description={
              loading ? "读取中…" : "还没有上传数据。上面选择一份表格即可开始。"
            }
          />
        )}
      </section>
    </>
  );
}
