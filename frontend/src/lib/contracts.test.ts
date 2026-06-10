import { describe, it, expect } from 'vitest'
import { isHttpsGitUrl, isSshGitUrl, isGitUrl, isGitUrlAllowedForAuth, isPinnedDockerImage } from './contracts'

describe('isHttpsGitUrl', () => {
  it('accepts https URLs', () => {
    expect(isHttpsGitUrl('https://github.com/user/repo.git')).toBe(true)
  })

  it('rejects http URLs', () => {
    expect(isHttpsGitUrl('http://github.com/user/repo.git')).toBe(false)
  })

  it('rejects SSH URLs', () => {
    expect(isHttpsGitUrl('git@github.com:user/repo.git')).toBe(false)
  })
})

describe('isSshGitUrl', () => {
  it('accepts SSH protocol URLs', () => {
    expect(isSshGitUrl('ssh://git@github.com/user/repo.git')).toBe(true)
  })

  it('accepts git@ style URLs', () => {
    expect(isSshGitUrl('git@github.com:user/repo.git')).toBe(true)
  })

  it('rejects HTTPS URLs', () => {
    expect(isSshGitUrl('https://github.com/user/repo.git')).toBe(false)
  })
})

describe('isGitUrl', () => {
  it('accepts HTTPS git URLs', () => {
    expect(isGitUrl('https://github.com/user/repo.git')).toBe(true)
  })

  it('accepts SSH git URLs', () => {
    expect(isGitUrl('git@github.com:user/repo.git')).toBe(true)
  })

  it('rejects invalid URLs', () => {
    expect(isGitUrl('not-a-url')).toBe(false)
  })
})

describe('isGitUrlAllowedForAuth', () => {
  it('allows HTTPS for token auth', () => {
    expect(isGitUrlAllowedForAuth('https://github.com/user/repo.git', 'token')).toBe(true)
  })

  it('rejects SSH for token auth', () => {
    expect(isGitUrlAllowedForAuth('git@github.com:user/repo.git', 'token')).toBe(false)
  })

  it('allows SSH for ssh_key auth', () => {
    expect(isGitUrlAllowedForAuth('git@github.com:user/repo.git', 'ssh_key')).toBe(true)
  })

  it('rejects HTTPS for ssh_key auth', () => {
    expect(isGitUrlAllowedForAuth('https://github.com/user/repo.git', 'ssh_key')).toBe(false)
  })
})

describe('isPinnedDockerImage', () => {
  it('accepts pinned images', () => {
    expect(isPinnedDockerImage('ubuntu:22.04')).toBe(true)
    expect(isPinnedDockerImage('myapp/backend:v1.2.3')).toBe(true)
  })

  it('rejects latest tag', () => {
    expect(isPinnedDockerImage('ubuntu:latest')).toBe(false)
  })

  it('rejects stable tag', () => {
    expect(isPinnedDockerImage('nginx:stable')).toBe(false)
  })

  it('rejects edge tag', () => {
    expect(isPinnedDockerImage('node:edge')).toBe(false)
  })

  it('rejects invalid format', () => {
    expect(isPinnedDockerImage('no-tag')).toBe(false)
  })
})
