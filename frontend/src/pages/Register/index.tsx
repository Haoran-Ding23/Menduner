import { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { useAccount } from "../../hooks/useEntitlements";

/**
 * Invite-code registration: the invite code is the authorisation for the trial, so there is no
 * open signup. A successful registration signs the customer in and starts the trial immediately.
 */
export default function RegisterPage() {
  const { register } = useAccount();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (values: {
    inviteCode: string;
    login: string;
    password: string;
    confirm: string;
    name: string;
    hotel?: string;
  }) => {
    if (values.password !== values.confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await register({
        inviteCode: values.inviteCode.trim(),
        login: values.login.trim(),
        password: values.password,
        name: values.name.trim(),
        hotel: values.hotel?.trim(),
      });
      navigate("/plans");
    } catch (registerError) {
      setError(registerError instanceof Error ? registerError.message : "注册失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="page-heading">
        <div className="eyebrow">客户账号</div>
        <h1>用邀请码注册</h1>
        <p>邀请码由我们提供；注册成功后立即开始四周专业版试用，试用不需要付款。</p>
      </div>
      <section className="panel auth-panel">
        {error && <Alert className="gap-bottom" type="error" showIcon message={error} />}
        <Form layout="vertical" onFinish={(values) => void submit(values)}>
          <Form.Item
            label="邀请码"
            name="inviteCode"
            rules={[{ required: true, message: "请输入邀请码" }]}
          >
            <Input placeholder="MND-XXXX-XXXX" autoComplete="off" />
          </Form.Item>
          <Form.Item
            label="登录名"
            name="login"
            rules={[
              { required: true, message: "请输入登录名" },
              { pattern: /^[A-Za-z0-9._-]{3,32}$/, message: "3–32 位字母、数字或 . _ -" },
            ]}
          >
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item label="称呼" name="name" rules={[{ required: true, message: "请输入称呼" }]}>
            <Input placeholder="例如:王经理" />
          </Form.Item>
          <Form.Item label="酒店(可选)" name="hotel">
            <Input placeholder="例如:市中心商务酒店" />
          </Form.Item>
          <Form.Item
            label="密码(至少 8 位)"
            name="password"
            rules={[{ required: true }, { min: 8, message: "至少 8 位" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="确认密码"
            name="confirm"
            rules={[{ required: true, message: "请再次输入密码" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting}>
            注册并开始试用
          </Button>
        </Form>
        <p className="muted gap-top">
          已有账号？<Link to="/login">登录</Link> · <Link to="/plans">查看套餐</Link>
        </p>
      </section>
    </div>
  );
}
