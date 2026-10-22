import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Select, Space, Table, Tag, message } from "antd";
import {
  PRIVATE_METRIC_LABELS,
  PRIVATE_METRIC_UNITS,
  addMember,
  importSpreadsheet,
  loadMembers,
  loadPrivateMetrics,
  removeMember,
  type ImportPreview,
  type MemberList,
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
/**
 * Who shares this hotel's ledger.
 *
 * A colleague registers first and is then added here; the backend moves them out of the empty
 * hotel their registration created and refuses if that hotel already holds data, so nothing is
 * destroyed by joining. Only an owner can add or remove, and the backend enforces that too -
 * hiding the buttons is a courtesy, not the rule.
 */
function Members() {
  const [state, setState] = useState<MemberList | null>(null);
  const [login, setLogin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setState(await loadMembers());
      setError("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "读取失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const add = async () => {
    setBusy(true);
    setError("");
    try {
      await addMember(login.trim());
      setLogin("");
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const drop = async (who: string) => {
    setBusy(true);
    setError("");
    try {
      await removeMember(who);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "移除失败");
    } finally {
      setBusy(false);
    }
  };

  if (error && !state) {
    return <Alert type="warning" showIcon message={error} />;
  }

  return (
    <>
      {error && <Alert className="gap-bottom" type="warning" showIcon message={error} />}
      <Table
        size="small"
        rowKey="login"
        dataSource={state?.members ?? []}
        pagination={false}
        columns={[
          { title: "账号", dataIndex: "login" },
          {
            title: "角色",
            width: 110,
            render: (_, row) => (
              <Tag color={row.role === "owner" ? "gold" : "default"}>
                {row.role === "owner" ? "负责人" : "成员"}
              </Tag>
            ),
          },
          {
            title: "加入时间",
            width: 130,
            render: (_, row) => row.added_at.slice(0, 10),
          },
          {
            title: "",
            width: 90,
            render: (_, row) =>
              state?.canManage && row.login !== state.login ? (
                <Button
                  size="small"
                  danger
                  type="link"
                  disabled={busy}
                  onClick={() => void drop(row.login)}
                >
                  移除
                </Button>
              ) : null,
          },
        ]}
      />
      {state?.canManage ? (
        <Space className="gap-top" wrap>
          <Input
            placeholder="对方注册时的登录名"
            aria-label="要加入本店的账号"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            style={{ width: 240 }}
          />
          <Button type="primary" loading={busy} disabled={!login.trim()} onClick={() => void add()}>
            邀请加入本店
          </Button>
          <small className="muted">对方需要先用邀请码注册账号</small>
        </Space>
      ) : (
        <p className="muted" style={{ marginTop: 12 }}>
          只有负责人可以添加或移除成员。
        </p>
      )}
    </>
  );
}

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
        <Space wrap className="gap-top">
          {/* Plain links: the browser sends the session cookie and the response is an
              attachment, so the file is downloaded without JavaScript needing to hold it. */}
          <Button href="/api/private/weekly.xlsx" download>
            导出周报 Excel
          </Button>
          <Button href="/api/private/weekly.pdf" download>
            导出周报 PDF
          </Button>
          <small className="muted">内容为上一完整周（周一至周日）</small>
        </Space>
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
          <h3 style={{ margin: 0 }}>本店成员</h3>
          <small className="muted">成员可查看本店全部数据；上传与成员管理由负责人操作</small>
        </div>
        <Members />
      </section>

      <section className="panel gap-top">
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
