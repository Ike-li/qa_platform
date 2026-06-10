import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../test/test-utils'
import { LanguageSwitcher } from './language-switcher'
import i18n from 'i18next'

describe('LanguageSwitcher', () => {
  it('renders when open', () => {
    render(<LanguageSwitcher isOpen={true} />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('renders when closed', () => {
    render(<LanguageSwitcher isOpen={false} />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('shows language label when open', () => {
    render(<LanguageSwitcher isOpen={true} />)
    expect(screen.getByText(/中文|English/)).toBeInTheDocument()
  })

  it('changes language on click', async () => {
    const changeLanguageSpy = vi.spyOn(i18n, 'changeLanguage')
    const { user } = render(<LanguageSwitcher isOpen={true} />)

    await user.click(screen.getByRole('button'))
    expect(changeLanguageSpy).toHaveBeenCalled()
  })
})
