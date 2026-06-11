/* eslint-disable react-refresh/only-export-components */
import type { ReactElement } from 'react'
import { render, type RenderOptions } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import i18n from 'i18next'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

// 创建测试用的 i18n 实例
i18n.init({
  lng: 'en',
  fallbackLng: 'en',
  ns: ['translation'],
  defaultNS: 'translation',
  resources: {
    en: {
      translation: {
        'priority.high': 'High',
        'priority.medium': 'Medium',
        'priority.low': 'Low',
        'time.seconds': '{{count}}s',
        'time.minutes': '{{count}}m',
        'time.justNow': 'just now',
        'time.minutesAgo': '{{count}} minutes ago',
        'time.hoursAgo': '{{count}} hours ago',
        'time.daysAgo': '{{count}} days ago',
        'runStatus.queued': 'queued',
        'runStatus.preparing': 'preparing',
        'runStatus.running': 'running',
        'runStatus.collecting': 'collecting',
        'runStatus.passed': 'passed',
        'runStatus.failed': 'failed',
        'runStatus.cancelled': 'cancelled',
        'runStatus.timed_out': 'timed out',
        'runStatus.unknown': 'unknown',
        'errors.pageNotFoundTitle': 'Page not found',
        'errors.pageNotFoundDescription': 'The page you are looking for does not exist.',
        'errors.goHome': 'Go home',
        'auth.signInTitle': 'Sign in',
        'auth.signInSubtitle': 'Enter your credentials',
        'auth.username': 'Username',
        'auth.password': 'Password',
        'auth.signIn': 'Sign in',
        'auth.signingIn': 'Signing in...',
        'auth.loginFailed': 'Login failed',
        'validation.usernameRequired': 'Username or email is required',
        'validation.passwordRequired': 'Password is required',
        'runs.failureTriage.title': 'Failure Triage',
        'runs.failureTriage.group.new': 'New failures',
        'runs.failureTriage.group.knownFlaky': 'Known flaky',
        'runs.failureTriage.group.persistent': 'Persistent failures',
        'runs.failureTriage.clusterCount': '×{{count}}',
        'runs.failureTriage.observing': 'Observing ({{count}} runs)',
        'runs.failureTriage.noMessage': '(no error message)',
        'runs.failureTriage.historyLabel': 'Last 10 observations',
      },
    },
  },
})

// 创建测试用的 QueryClient
export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  queryClient?: QueryClient
  withRouter?: boolean
}

function customRender(
  ui: ReactElement,
  options?: CustomRenderOptions
) {
  const { queryClient = createTestQueryClient(), withRouter = false, ...renderOptions } = options || {}

  const Wrapper = ({ children }: { children: React.ReactNode }) => {
    let content = (
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          {children}
        </I18nextProvider>
      </QueryClientProvider>
    )

    if (withRouter) {
      content = <BrowserRouter>{content}</BrowserRouter>
    }

    return content
  }

  return {
    user: userEvent.setup(),
    ...render(ui, {
      wrapper: Wrapper,
      ...renderOptions,
    }),
  }
}

// 等待异步加载完成的辅助函数
export const waitForLoadingToFinish = () =>
  new Promise((resolve) => setTimeout(resolve, 0))

// Re-export everything
export * from '@testing-library/react'

// Override render method
export { customRender as render }
