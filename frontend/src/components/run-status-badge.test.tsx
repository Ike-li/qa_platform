import { describe, it, expect } from 'vitest'
import { render, screen } from '../test/test-utils'
import { RunStatusBadge } from './run-status-badge'

describe('RunStatusBadge', () => {
  it('renders queued status', () => {
    render(<RunStatusBadge status="queued" />)
    expect(screen.getByText('queued')).toBeInTheDocument()
  })

  it('renders running status', () => {
    render(<RunStatusBadge status="running" />)
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  it('renders passed status', () => {
    render(<RunStatusBadge status="passed" />)
    expect(screen.getByText('passed')).toBeInTheDocument()
  })

  it('renders failed status', () => {
    render(<RunStatusBadge status="failed" />)
    expect(screen.getByText('failed')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<RunStatusBadge status="passed" className="custom" />)
    expect(container.querySelector('.custom')).toBeInTheDocument()
  })
})
