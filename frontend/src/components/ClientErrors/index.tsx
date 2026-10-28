import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Collapse, Space, Table, Tag, Typography, message } from "antd";
import { loadClientErrors, type StoredClientError } from "../../services/api";

/**
 * Browser-side errors recorded by the ErrorBoundary and the global handlers.
 *
 * This exists because the failure it reports looked like nothing at all. A crash with no error
 * boundary unmounts the React tree and leaves a blank white page; on a phone there is no
 * console to open, so the only available report was "知识图谱打不开" with no way to find out why.
 * The report now lands in the database, and this is where it is read from a desktop.
 */
export default function ClientErrors() {
  const [rows, setRows] = useState<StoredClientError[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await loadClientErrors(50));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取前端错误失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** 手动刷新：必须给一句反馈，否则空列表下点击看起来毫无反应。 */
  const reload = useCallback(async () => {
    await load();
    message.success("已重新检查前端错误上报");
  }, [load]);

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        message={error}
        action={
          <Button size="small" loading={loading} onClick={() => void reload()}>
            重试
          </Button>
        }
      />
    );
  }
  if (!loading && !rows.length) {
    // 空状态下也要保留刷新入口：否则"刷新"按钮会整块消失，
    // 用户既看不到按钮，也无法主动再检查一次。
    return (
      <Alert
        type="success"
        showIcon
        message="没有记录到前端错误"
        description="页面崩溃时会自动上报到这里，包括手机上的错误。"
        action={
          <Button size="small" loading={loading} onClick={() => void reload()}>
            重新检查
          </Button>
        }
      />
    );
  }

  return (
    <>
      <div className="panel-heading">
        <Space wrap>
          <strong>前端错误</strong>
          <Tag color={rows.length ? "red" : "green"}>{rows.length} 条</Tag>
          {(() => {
            // 本地开发（127.0.0.1 / localhost）与线上的报错要分开看，避免把噪音当线上故障
            const local = rows.filter((r) => /127\.0\.0\.1|localhost/.test(r.source ?? "")).length;
            if (!local) return null;
            return <Tag>{`其中本地开发 ${local} 条`}</Tag>;
          })()}
          <small className="muted">
            手机或电脑上打开页面出错时会自动记录，含错误信息、堆栈和屏幕尺寸。
          </small>
        </Space>
        <Button size="small" loading={loading} onClick={() => void reload()}>
          刷新
        </Button>
      </div>
      <Table<StoredClientError>
        rowKey="id"
        dataSource={rows}
        size="small"
        loading={loading}
        pagination={rows.length > 8 ? { pageSize: 8 } : false}
        scroll={{ x: 800 }}
        expandable={{
          expandedRowRender: (row) => (
            <Typography.Paragraph
              style={{ whiteSpace: "pre-wrap", fontSize: 11, margin: 0 }}
              copyable
            >
              {`页面: ${row.page ?? "?"}
尺寸: ${row.viewport ?? "?"}
来源: ${row.source ?? "?"}
UA: ${row.user_agent ?? "?"}${
                row.extra && (row.extra.filename || row.extra.src)
                  ? `
出错文件: ${String(row.extra.filename ?? row.extra.src)}${
                      row.extra.lineno ? `:${row.extra.lineno}` : ""
                    }${row.extra.colno ? `:${row.extra.colno}` : ""}`
                  : ""
              }

${row.stack ?? "（没有堆栈）"}`}
            </Typography.Paragraph>
          ),
          // The stack is the useful part, so the common case opens by itself.
          defaultExpandedRowKeys: rows.length === 1 ? [rows[0].id] : [],
          rowExpandable: (row) => Boolean(row.stack),
        }}
        columns={[
          {
            title: "时间",
            width: 165,
            render: (_, r) => new Date(r.occurred_at).toLocaleString("zh-CN"),
          },
          { title: "页面", dataIndex: "page", width: 110 },
          { title: "尺寸", dataIndex: "viewport", width: 90 },
          {
            title: "错误",
            render: (_, r) => (
              <Space direction="vertical" size={0}>
                <span>{r.message ?? "（无信息）"}</span>
                <small className="muted">{r.source ?? ""}</small>
              </Space>
            ),
          },
        ]}
      />
      <Collapse
        size="small"
        ghost
        items={[
          {
            key: "help",
            label: "手机上报错怎么看？",
            children: (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                1. 手机上打开出错页面，触发错误后回到电脑刷新本页。
                <br />
                2. 展开某一行可以看到完整堆栈，右上角按钮可复制。
                <br />
                3. 如果什么都没记录到，说明不是 JavaScript 错误 —— 更可能是网络或服务器问题，
                用下面的「采集来源状态」和后端日志排查。
              </Typography.Paragraph>
            ),
          },
        ]}
      />
    </>
  );
}
