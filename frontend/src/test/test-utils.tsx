import { ReactElement } from 'react'
import { render, RenderOptions } from '@testing-library/react'
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
      },
    },
  },
})

interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  initialI18nStore?: Record<string, any>
  initialLanguage?: string
}

function customRender(
  ui: ReactElement,
  options?: CustomRenderOptions
) {
  return render(ui, {
    wrapper: ({ children }) => (
      <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
    ),
    ...options,
  })
}

export * from '@testing-library/react'
export { customRender as render }
