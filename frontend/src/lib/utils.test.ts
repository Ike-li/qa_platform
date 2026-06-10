import { describe, it, expect } from 'vitest'
import { cn, isSafeArtifactUrl } from './utils'

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('handles conditional classes', () => {
    expect(cn('foo', false && 'bar', 'baz')).toBe('foo baz')
  })

  it('merges tailwind classes', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })
})

describe('isSafeArtifactUrl', () => {
  it('accepts https URLs', () => {
    expect(isSafeArtifactUrl('https://example.com/file.txt')).toBe(true)
  })

  it('accepts http URLs', () => {
    expect(isSafeArtifactUrl('http://example.com/file.txt')).toBe(true)
  })

  it('rejects URLs with username', () => {
    expect(isSafeArtifactUrl('https://user@example.com/file.txt')).toBe(false)
  })

  it('rejects URLs with password', () => {
    expect(isSafeArtifactUrl('https://user:pass@example.com/file.txt')).toBe(false)
  })

  it('rejects non-http protocols', () => {
    expect(isSafeArtifactUrl('ftp://example.com/file.txt')).toBe(false)
    expect(isSafeArtifactUrl('file:///etc/passwd')).toBe(false)
  })

  it('rejects invalid URLs', () => {
    expect(isSafeArtifactUrl('not a url')).toBe(false)
  })
})
