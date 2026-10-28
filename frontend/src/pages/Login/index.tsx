import { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import {
  BarChartOutlined,
  CheckCircleOutlined,
  LockOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Link, useNavigate } from "react-router-dom";
import { useAccount } from "../../hooks/useEntitlements";
import { FILING_MODE } from "../../config";

/**
 * Customer sign-in.
 *
 * Separate from the operator review console (HTTP Basic): this is a product account, and the
 * session lives in an HttpOnly cookie managed by the backend.
 *
 * Laid out as a two-panel screen - product on the left, form on the right - which is the shape
 * most subscription products use for this page. The reason is not decoration: a person arriving
 * here is often seeing the product for the first time, and a bare rectangle with two fields
 * gives them nothing to decide with. The right-hand panel is the only interactive area, so the
 * eye has one place to go once the form starts.
 */
export default function LoginPage() {
  const { login } = useAccount();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (values: { login: string; password: string }) => {
    setSubmitting(true);
    setError("");
    try {
      await login(values.login, values.password);
      navigate("/map");
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="signin">
      <aside className="signin-aside">
        <div className="signin-brand">
          <span className="signin-logo">M</span>
          <div>
            <strong>Menduner</strong>
            <small>城市活动情报</small>
          </div>
        </div>

        <h2 className="signin-pitch">
          把城市的活动，
          <br />
          变成酒店能执行的判断。
        </h2>

        <ul className="signin-points">
          <li>
            <BarChartOutlined />
            <span>活动、场馆与周边酒店，按地区聚合，一眼看清</span>
          </li>
          <li>
            <CheckCircleOutlined />
            <span>每条数据保留来源与核验状态，可点回原文核对</span>
          </li>
          <li>
            <LockOutlined />
            <span>本店经营数据独立存放，只在本店账号下可见</span>
          </li>
        </ul>

        <small className="signin-note">
          公开活动信息来自政府、场馆与文旅渠道的公开页面
        </small>
      </aside>

      <main className="signin-main">
        <div className="signin-card">
          <h1>登录</h1>
          <p className="signin-sub">
            登录后使用本店经营数据、成员管理与周报导出。
          </p>

          {error && (
            <Alert className="gap-bottom" type="error" showIcon message={error} />
          )}

          <Form layout="vertical" requiredMark={false} onFinish={(values) => void submit(values)}>
            <Form.Item
              label="登录名"
              name="login"
              rules={[{ required: true, message: "请输入登录名" }]}
            >
              <Input
                size="large"
                autoComplete="username"
                prefix={<UserOutlined className="signin-field-icon" />}
                placeholder="例如：menduner"
              />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                size="large"
                autoComplete="current-password"
                prefix={<LockOutlined className="signin-field-icon" />}
                placeholder="请输入密码"
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={submitting}
              className="signin-submit"
            >
              登录
            </Button>
          </Form>

          {/* A real, working demo account. It owns its own tenant holding synthetic figures, so
              anyone can try the product end to end without touching public data or another
              hotel's ledger. */}
          <div className="signin-hint">
            <strong>演示账号</strong>
            <code>登录名 menduner　密码 123456</code>
            <small>可直接登录。里面是示例数据，不含任何真实酒店信息。</small>
          </div>

          <p className="signin-links">
            还没有账号？<Link to="/register">用邀请码注册</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
