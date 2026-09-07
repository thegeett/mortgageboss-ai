"use client";

import { useCallback, useEffect, useState } from "react";

export const NAV_COOKIE = "ledger-nav";

/**
 * ⌘B collapse for the context column (LP-UI-008).
 *
 * `data-nav` on `<html>` is the SINGLE source of truth. The server stamps it from
 * a cookie so the collapsed state is right in the first byte; the cookie is only
 * that attribute's persistence, and the React value below is only its mirror for
 * rendering `aria-expanded`. Neither decides anything.
 *
 * That ordering is the point. `toggle` used to compute the next state from the
 * React value and write the DOM from it, which made three producers of one fact
 * out of what is really one — and any divergence would have cost a silent no-op
 * press. Reading the attribute means the thing that drives the pixels is also the
 * thing that decides.
 *
 * The width itself is CSS (`[data-nav="collapsed"] { --nav-w: 0 }`), so a
 * collapsed sidebar is collapsed in the first paint. Storing it in React state
 * and applying it in an effect would re-expand the column on every navigation
 * and flash it on every refresh, which the ticket calls out as infuriating in an
 * all-day tool — correctly.
 */
export function useNavCollapse({ enabled = true }: { enabled?: boolean } = {}) {
  const [collapsed, setCollapsed] = useState(false);

  // Adopt whatever the server already stamped, without changing it.
  useEffect(() => {
    setCollapsed(document.documentElement.dataset.nav === "collapsed");
  }, []);

  const toggle = useCallback(() => {
    const root = document.documentElement;
    const next = root.dataset.nav !== "collapsed";
    if (next) root.dataset.nav = "collapsed";
    else root.removeAttribute("data-nav");
    // Expanded is the DEFAULT, and the server tests for "collapsed" exactly — so
    // expanding deletes the cookie rather than writing "expanded". A cookie whose
    // only value means "the default" is a second way to spell no cookie, and the
    // two would eventually disagree about which is canonical.
    document.cookie = next
      ? // `max-age` a year, `SameSite=Lax` so it rides a normal navigation. Not
        // httpOnly by necessity: the client half of the pair has to write it.
        `${NAV_COOKIE}=collapsed;path=/;max-age=31536000;samesite=lax`
      : `${NAV_COOKIE}=;path=/;max-age=0;samesite=lax`;
    // Mirrors, after the fact. Side effects never belong in a setState updater:
    // React may invoke it twice, or discard the render it ran in, and the DOM
    // write and the cookie would already have happened.
    setCollapsed(next);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "b" && event.key !== "B") return;
      if (!event.metaKey && !event.ctrlKey) return;
      // Don't fight a browser or OS binding the user meant for something else.
      if (event.altKey || event.shiftKey) return;
      // In rich text ⌘B means BOLD, and stealing it there would break the one
      // place the user definitely meant something else. Plain inputs and
      // textareas are deliberately NOT excluded: ⌘B does nothing native in them,
      // so a processor who presses it while a field has focus meant this.
      if (event.target instanceof HTMLElement && event.target.isContentEditable) return;
      // Nothing to toggle on a route with no context column. Silently flipping
      // hidden state from a screen that cannot show the result is worse than the
      // shortcut doing nothing — the rail's button is hidden there for the same
      // reason, and a shortcut that disagrees with the visible affordance is
      // just an invisible one.
      if (!enabled) return;
      event.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggle, enabled]);

  return { collapsed, toggle };
}
