// vitest 5 把 Assertion 改成 Assertion<R, T>，而 @testing-library/jest-dom
// （截至 7.0.1）自带的 vitest 类型仍按单参数 Assertion<T> 扩展，合并不上，
// toBeInTheDocument 等断言在 tsc 下全部报不存在。改挂到 vitest 为自定义断言
// 预留的 Matchers<R, T> 扩展点上。jest-dom 修好后可删掉本文件，改为在
// setup.ts 里 import '@testing-library/jest-dom/vitest'。
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers'

// 声明合并要求类型参数与 vitest 原声明一致（T 因此保留），且只能继承、没有自有成员；
// E 用来接收 expect.stringContaining() 这类非对称匹配器，与 jest-dom 自身声明一致取 any
/* eslint-disable @typescript-eslint/no-empty-object-type, @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
declare module 'vitest' {
  interface Matchers<R extends void | Promise<void> = void | Promise<void>, T = unknown>
    extends TestingLibraryMatchers<any, R> {}
}
/* eslint-enable @typescript-eslint/no-empty-object-type, @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
