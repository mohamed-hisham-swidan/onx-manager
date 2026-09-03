import "@testing-library/jest-dom/vitest";

import { beforeEach } from "vitest";

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, String(value)); },
    removeItem: (key: string) => { store.delete(key); },
    clear: () => { store.clear(); },
    get length() { return store.size; },
    key: (index: number) => [...store.keys()][index] ?? null,
  };
}

const mockLocalStorage = createStorageMock();
const mockSessionStorage = createStorageMock();

Object.defineProperty(globalThis, "localStorage", {
  value: mockLocalStorage,
  configurable: true,
  writable: true,
});
Object.defineProperty(globalThis, "sessionStorage", {
  value: mockSessionStorage,
  configurable: true,
  writable: true,
});

if (typeof window !== "undefined") {
  Object.defineProperty(window, "localStorage", {
    value: mockLocalStorage,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "sessionStorage", {
    value: mockSessionStorage,
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  mockLocalStorage.clear();
  mockSessionStorage.clear();
});

window.matchMedia = (query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
});
