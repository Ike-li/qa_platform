import '@testing-library/jest-dom'
import { beforeAll, afterEach, afterAll } from 'vitest'
import { setupServer } from 'msw/node'
import { handlers } from './mocks/handlers'

// 创建 MSW server
export const server = setupServer(...handlers)

// 启动 server
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))

// 每个测试后重置 handlers
afterEach(() => server.resetHandlers())

// 所有测试完成后关闭 server
afterAll(() => server.close())

