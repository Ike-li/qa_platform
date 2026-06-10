import { describe, it, expect } from 'vitest'
import { render, screen } from '../test/test-utils'
import { BranchBadge } from './branch-badge'

describe('BranchBadge', () => {
  it('renders branch name', () => {
    render(<BranchBadge branch="main" />)
    expect(screen.getByText('main')).toBeInTheDocument()
  })

  it('renders different branch names', () => {
    render(<BranchBadge branch="feature/test" />)
    expect(screen.getByText('feature/test')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<BranchBadge branch="main" className="custom" />)
    expect(container.querySelector('.custom')).toBeInTheDocument()
  })
})
