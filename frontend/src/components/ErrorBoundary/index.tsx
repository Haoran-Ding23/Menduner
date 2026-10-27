import { Component, type ErrorInfo, type ReactNode } from "react";
import { Alert, Button, Space, Typography, Collapse } from "antd";
import { reportClientError } from "../../services/api";

/**
 * Renders the error instead of unmounting the page.
 *
 * The app had no error boundary, so any exception in a lazily-loaded page took the whole tree
 * down and left a blank white screen. That is the worst failure mode here: the person holding
 * the phone cannot open a console, so "知识图谱打不开" was all they could report. A boundary turns
 * that into a readable message with the stack, and the same details are POSTed to the server.
 *
 * Deliberately a class: getDerivedStateFromError has no hook equivalent.
 */
export default class ErrorBoundary extends Component<
  { children: ReactNode; where?: string },
  { error: Error | null; info: ErrorInfo | null }
> {
  state: { error: Error | null; info: ErrorInfo | null } = {
    error: null,
    info: null,
  };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info });
    // Fire and forget: reporting must never itself throw and hide the original error.
    void reportClientError({
      message: error.message,
      source: this.props.where ?? "react",
      stack: `${error.stack ?? ""}\n--- component stack ---${info.componentStack ?? ""}`,
      page: window.location.pathname,
      userAgent: navigator.userAgent,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
    }).catch(() => {});
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;
    // antd's Alert already exposes role="alert"; adding it to the wrapper duplicates it.
    return (
      <div className="crash-panel">
        <Alert
          type="error"
          showIcon
          message={`页面出错了：${this.props.where ?? "未知位置"}`}
          description={
            <Space direction="vertical" style={{ width: "100%" }}>
              <Typography.Text code copyable>
                {error.message || String(error)}
              </Typography.Text>
              <Typography.Text type="secondary">
                这个错误已经记录到服务器，我们会跟进处理。你可以先刷新页面重试。
              </Typography.Text>
              <Collapse
                size="small"
                items={[
                  {
                    key: "stack",
                    label: "技术细节（点开可复制）",
                    children: (
                      <Typography.Paragraph
                        style={{ whiteSpace: "pre-wrap", fontSize: 11 }}
                        copyable
                      >
                        {`${error.stack ?? ""}\n${info?.componentStack ?? ""}`}
                      </Typography.Paragraph>
                    ),
                  },
                ]}
              />
              <Space>
                <Button
                  size="small"
                  type="primary"
                  onClick={() => this.setState({ error: null, info: null })}
                >
                  重试
                </Button>
                <Button size="small" onClick={() => window.location.reload()}>
                  刷新页面
                </Button>
                {/* Going home is the reliable escape: the failing page may crash again on
                    re-render, and without this the user is stuck on the error screen. */}
                <Button
                  size="small"
                  onClick={() => {
                    window.location.href = "/map";
                  }}
                >
                  返回地图
                </Button>
              </Space>
            </Space>
          }
        />
      </div>
    );
  }
}
