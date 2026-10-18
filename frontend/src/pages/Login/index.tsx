import { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { useAccount } from "../../hooks/useEntitlements";

/**
 * Customer sign-in. Separate from the operator review console (HTTP Basic): this is a product
 * account, and the session lives in an HttpOnly cookie managed by the backend.
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
      navigate("/plans");
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">客户账号</div>
        <h1>登录</h1>
        <p>登录后查看套餐、试用剩余时间和开通申请。</p>
      </div>
      <section className="panel" style={{ maxWidth: 520 }}>
        {error && <Alert className="gap-bottom" type="error" showIcon message={error} />}
        <Form layout="vertical" onFinish={(values) => void submit(values)}>
          <Form.Item label="登录名" name="login" rules={[{ required: true, message: "请输入登录名" }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting}>
            登录
          </Button>
        </Form>
        <p className="muted gap-top">
          还没有账号？<Link to="/register">用邀请码注册试用</Link> · <Link to="/plans">查看套餐</Link>
        </p>
      </section>
    </>
  );
}
