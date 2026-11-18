import '@testing-library/jest-dom/vitest'

// jsdom не умеет то, что нужно React Flow: подставляем заглушки.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
globalThis.DOMMatrixReadOnly ??= class {
  m22 = 1
} as unknown as typeof DOMMatrixReadOnly
