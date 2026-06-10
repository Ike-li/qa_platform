/* eslint-disable react-refresh/only-export-components */
import type { ReactElement } from 'react'
import { render, type RenderOptions } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import i18n from 'i18next'

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
      },
    },
  },
})

function customRender(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return {
    user: userEvent.setup(),
    ...render(ui, {
      wrapper: ({ children }) => (
        <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
      ),
      ...options,
    }),
  }
}

// Re-export everything
export * from '@testing-library/react'

// Override render method
export { customRender as render }
