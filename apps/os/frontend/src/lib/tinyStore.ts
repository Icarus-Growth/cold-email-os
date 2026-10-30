/* A minimal external store for React (useSyncExternalStore). */
import { useSyncExternalStore } from 'react';

export interface TinyStore<T> {
  get(): T;
  set(next: T | ((prev: T) => T)): void;
  subscribe(fn: () => void): () => void;
  use(): T;
}

export function tinyStore<T>(initial: T): TinyStore<T> {
  let value = initial;
  const subs = new Set<() => void>();
  const store: TinyStore<T> = {
    get: () => value,
    set(next) {
      const v = typeof next === 'function' ? (next as (p: T) => T)(value) : next;
      if (Object.is(v, value)) return;
      value = v;
      subs.forEach((f) => f());
    },
    subscribe(fn) { subs.add(fn); return () => { subs.delete(fn); }; },
    use() { return useSyncExternalStore(store.subscribe, store.get, store.get); },
  };
  return store;
}
