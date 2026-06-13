"use client";

import { useEffect, useState } from "react";

/**
 * Returns `value` delayed by `delayMs` — for debouncing search input so we don't
 * fire a request on every keystroke (LP-31).
 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);

  return debounced;
}
