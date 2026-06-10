import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../test/test-utils'
import { BrowserRouter } from 'react-router-dom'
import Login from './login'

vi.mock('../hooks/use-auth', () => ({
  useAuth: () => ({
    login: vi.fn(),
  }),
}))

describe('Login', () => {
  it('renders login form', () => {
    render(
      <BrowserRouter>
        <Login />
      </BrowserRouter>
    )
    expect(screen.getByText('Sign in')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })

  it('shows validation errors for empty fields', async () => {
    const { user } = render(
      <BrowserRouter>
        <Login />
      </BrowserRouter>
    )

    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Username or email is required')).toBeInTheDocument()
    expect(await screen.findByText('Password is required')).toBeInTheDocument()
  })
})
