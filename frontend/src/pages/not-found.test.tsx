import { describe, it, expect } from 'vitest'
import { render, screen } from '../test/test-utils'
import { BrowserRouter } from 'react-router-dom'
import NotFound from './not-found'

describe('NotFound', () => {
  it('renders 404 message', () => {
    render(
      <BrowserRouter>
        <NotFound />
      </BrowserRouter>
    )
    expect(screen.getByText('404')).toBeInTheDocument()
  })

  it('renders home link', () => {
    render(
      <BrowserRouter>
        <NotFound />
      </BrowserRouter>
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '/projects')
  })
})
