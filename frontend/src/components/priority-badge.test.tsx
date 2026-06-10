import { describe, it, expect } from 'vitest'
import { render, screen } from '../test/test-utils'
import { PriorityBadge } from './priority-badge'

describe('PriorityBadge', () => {
  it('displays high priority', () => {
    render(<PriorityBadge priority={0} />)
    expect(screen.getByText('High')).toBeInTheDocument()
  })

  it('displays medium priority', () => {
    render(<PriorityBadge priority={1} />)
    expect(screen.getByText('Medium')).toBeInTheDocument()
  })

  it('displays low priority', () => {
    render(<PriorityBadge priority={2} />)
    expect(screen.getByText('Low')).toBeInTheDocument()
  })

  it('defaults to medium for unknown priority', () => {
    render(<PriorityBadge priority={99} />)
    expect(screen.getByText('Medium')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<PriorityBadge priority={0} className="custom-class" />)
    expect(container.querySelector('.custom-class')).toBeInTheDocument()
  })
})
