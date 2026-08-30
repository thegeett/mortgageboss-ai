"use client";

import { useCallback, useEffect, useState } from "react";

export const NAV_COOKIE = "ledger-nav";

/**
 * ⌘B collapse for the context column (LP-UI-008).
 *
 * The state lives in TWO places on purpose, and neither is React state that the
 * server cannot see:
 *
 *  - a cookie, so the SERVER knows the answer while rendering the first byte;
 *  - `data-nav` on `<html>`, which the server stamps from that cookie and this
 *    hook flips thereafter.
 *
 * The width itself is CSS (`[data-nav="collapsed"] { --nav-w: 0 }`), so a
 * collapsed sidebar is collapsed in the first paint. Storing it in React state
 * and applying it in an effect would re-expand the column on every navigation
 * and flash it on every refresh, which the ticket calls out as infuriating in an
 * all-day tool — correctly.
 */
export function useNavCollapse() {
  const [collapsed, setCollapsed] = useState(false);

  // Adopt whatever the server already stamped, without changing it.
  useEffect(() => {
    setCollapsed(document.documentElement.dataset.nav === "collapsed");
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((previous) => {
      const next = !previous;
      const root = document.documentElement;
      if (next) root.dataset.nav = "collapsed";
      else root.removeAttribute("data-nav");
      // `max-age` a year, `SameSite=Lax` so it rides a normal navigation. Not
      // httpOnly by necessity: the client half of the pair has to write it.
      document.cookie = `${NAV_COOKIE}=${next ? "collapsed" : "expanded"};path=/;max-age=31536000;samesite=lax`;
      return next;
    });
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "b" && event.key !== "B") return;
      if (!event.metaKey && !event.ctrlKey) return;
      // Don't fight a browser or OS binding the user meant for something else.
      if (event.altKey || event.shiftKey) return;
      event.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggle]);

  return { collapsed, toggle };
}
