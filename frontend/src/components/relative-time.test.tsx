import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '../test/test-utils'
import { RelativeTime } from './relative-time'

describe('RelativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders just now for recent dates', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    const recent = new Date('2024-01-01T11:59:30Z')

    render(<RelativeTime date={recent} />)
    expect(screen.getByText('just now')).toBeInTheDocument()
  })

  it('renders minutes ago', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    const fiveMinutesAgo = new Date('2024-01-01T11:55:00Z')

    render(<RelativeTime date={fiveMinutesAgo} />)
    expect(screen.getByText(/5.*ago/)).toBeInTheDocument()
  })

  it('accepts string dates', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)

    render(<RelativeTime date="2024-01-01T11:59:30Z" />)
    expect(screen.getByText('just now')).toBeInTheDocument()
  })

  it('renders time element with datetime attribute', () => {
    const date = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(date)

    render(<RelativeTime date={date} />)
    const timeElement = screen.getByText(/just now|ago/i)
    expect(timeElement.tagName).toBe('TIME')
    expect(timeElement).toHaveAttribute('datetime')
  })
})
