import { describe, it, expect } from 'vitest'
import { render, screen } from '../test/test-utils'
import { DurationDisplay } from './duration-display'

describe('DurationDisplay', () => {
  it('displays dash for null', () => {
    render(<DurationDisplay seconds={null} />)
    expect(screen.getByText('-')).toBeInTheDocument()
  })

  it('displays dash for undefined', () => {
    render(<DurationDisplay seconds={undefined} />)
    expect(screen.getByText('-')).toBeInTheDocument()
  })

  it('displays seconds for duration < 60s', () => {
    render(<DurationDisplay seconds={45} />)
    expect(screen.getByText('45s')).toBeInTheDocument()
  })

  it('displays minutes and seconds for duration >= 60s', () => {
    render(<DurationDisplay seconds={125} />)
    expect(screen.getByText(/2m/)).toBeInTheDocument()
    expect(screen.getByText(/5s/)).toBeInTheDocument()
  })

  it('rounds seconds correctly', () => {
    render(<DurationDisplay seconds={45.6} />)
    expect(screen.getByText('46s')).toBeInTheDocument()
  })
})
