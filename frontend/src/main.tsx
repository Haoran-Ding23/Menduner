import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { PlatformProvider } from './hooks/usePlatform';
import App from './App';
import { reportClientError } from './services/api';
import './styles/global.css';

dayjs.locale('zh-cn');

/**
 * Catch what the ErrorBoundary cannot.
 *
 * A boundary only sees errors thrown while React renders. Failures in an event handler, in a
 * timer, or an unhandled promise rejection bypass it entirely and would leave the page silently
 * broken. These handlers POST the same report, so the server has one place to look.
 */
function describe(reason: unknown): { message: string; stack?: string } {
  if (reason instanceof Error) {
    return { message: reason.message || reason.name, stack: reason.stack };
  }
  if (typeof reason === 'string') return { message: reason };
  try {
    return { message: JSON.stringify(reason) };
  } catch {
    return { message: String(reason) };
  }
}

function report(reason: unknown, source: string) {
  const { message, stack } = describe(reason);
  void reportClientError({
    message,
    source,
    stack,
    page: window.location.pathname,
    userAgent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
  }).catch(() => {
    /* the reporter must never be able to make things worse */
  });
}

window.addEventListener('error', (event) => {
  // Resource load failures (a script or image that 404s) also fire here and carry no error
  // object; they are reported with the tag name so they are distinguishable in the log.
  if (event.error) report(event.error, 'window.error');
  else if (event.target && event.target !== window) {
    const el = event.target as HTMLElement;
    report(
      { message: `资源加载失败: ${el.tagName} ${(el as HTMLScriptElement).src ?? ""}` },
      'resource',
    );
  }
});

window.addEventListener('unhandledrejection', (event) => {
  report(event.reason, 'unhandledrejection');
});

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#1677ff', borderRadius: 10, fontFamily: 'Inter, "Microsoft YaHei", system-ui, sans-serif' } }}><BrowserRouter><PlatformProvider><App /></PlatformProvider></BrowserRouter></ConfigProvider></React.StrictMode>);
