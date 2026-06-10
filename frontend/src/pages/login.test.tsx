import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '../test/test-utils'
import { BrowserRouter } from 'react-router-dom'
import Login from './login'
import { server } from '../test/setup'
import { http, HttpResponse } from 'msw'

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

  it("shows error on login failure", async () => {
    server.use(
      http.post("/api/v1/auth/login", () => {
        return HttpResponse.json(
          { detail: "Invalid credentials" },
          { status: 401 }
        );
      })
    );

    const { user } = render(
      <BrowserRouter>
        <Login />
      </BrowserRouter>
    );

    const usernameInput = screen.getByLabelText(/username/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitButton = screen.getByRole("button", { name: /sign in/i });

    await user.type(usernameInput, "wrong");
    await user.type(passwordInput, "wrong");
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });
})
