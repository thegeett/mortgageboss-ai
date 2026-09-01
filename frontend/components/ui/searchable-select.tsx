"use client";

import { cn } from "@/lib/utils";
import { Check, ChevronDown, Search } from "lucide-react";
import * as React from "react";

export interface SearchableOption {
  value: string;
  label: string;
  /** Optional grouping header, e.g. a document category. */
  group?: string;
}

/**
 * A type-to-search picker for lists too long to scroll (LP-638).
 *
 * WHY NOT THE NATIVE `<select>` this replaces for one control. `components/ui/select.tsx` is a
 * styled native select, chosen deliberately — accessible and mobile-friendly with no dependency —
 * and it stays right for the short, fixed lists it serves. It is wrong for 164 document types: a
 * native select cannot be searched by anything but first letter, so finding "Closing disclosure"
 * means scrolling a flat list of every type in the catalog.
 *
 * NO NEW DEPENDENCY, for the reason select.tsx gives. An input, a filtered list, and the keyboard
 * handling written out — arrows to move, Enter to choose, Escape to close, blur to dismiss.
 */
export function SearchableSelect({
  options,
  value,
  onChange,
  onOpenChange,
  label,
  disabled,
  placeholder = "Search…",
  emptyMessage = "No matches",
  id: providedId,
}: {
  options: SearchableOption[];
  value: string | null;
  onChange: (value: string) => void;
  /**
   * Told whenever the list opens or closes, so an ancestor that also handles Escape can
   * stand down while it is open — see the note on the Escape branch below.
   */
  onOpenChange?: (open: boolean) => void;
  /**
   * The control's accessible name, REQUIRED (LP-638 review).
   *
   * Not optional, because the first version had no name at all: `aria-label` and
   * `aria-labelledby` were both absent, so a screen reader announced an unlabelled combobox. The
   * two `useSemanticElements` suppressions below are correct — the ARIA 1.2 combobox pattern is
   * the right one here — but defending them is not the same as being accessible, and the missing
   * name was the larger failure of the two. Making it a required prop is what stops the next
   * caller repeating it.
   */
  label: string;
  disabled?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  /** Optional — one is generated when absent, since the ARIA wiring depends on it. */
  id?: string;
}) {
  // `aria-controls`, `aria-activedescendant`, the option ids and the highlight-scroll all hang off
  // this id. It was optional, so a caller omitting it got a combobox that announced no active
  // option and did not follow the keyboard — with nothing failing (LP-638 review). Generated when
  // absent, so the contract holds either way.
  const generatedId = React.useId();
  const id = providedId ?? generatedId;

  const [open, setOpenState] = React.useState(false);
  const setOpen = React.useCallback(
    (next: boolean) => {
      setOpenState(next);
      onOpenChange?.(next);
    },
    [onOpenChange],
  );
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const selected = options.find((option) => option.value === value) ?? null;

  const matches = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    // Matches the LABEL or the underlying slug, so "closing" and "closing_disclosure" both work —
    // a processor reading a slug elsewhere in the product can paste it straight in.
    return options.filter(
      (option) =>
        option.label.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle),
    );
  }, [options, query]);

  // Keep the highlight inside the list as it shrinks under typing. Reset in the change handler
  // rather than an effect: the effect declared `query` as a dependency while not reading it, and
  // the reset belongs with the keystroke that causes it anyway.

  // CLOSING ALWAYS CLEARS THE QUERY (LP-638 review). The outside-click path used to leave it set:
  // the input correctly reverted to showing the selected label, so nothing looked wrong — and then
  // refocusing restored the abandoned search and its filtered list. On a 164-type catalog a
  // processor came back to a picker that appeared to hold one option, with no visible reason why.
  // Every exit resets, so the control opens in the same state however it was left.
  const close = React.useCallback(() => {
    setOpen(false);
    setQuery("");
    setActive(0);
  }, [setOpen]);

  // Close on an outside click. Blur alone is not enough: clicking an option blurs the input before
  // the click lands, so the list would close before it could be chosen.
  React.useEffect(() => {
    if (!open) return;
    function onDocumentDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) close();
    }
    document.addEventListener("mousedown", onDocumentDown);
    return () => document.removeEventListener("mousedown", onDocumentDown);
  }, [open, close]);

  // Keep the highlighted option visible. `aria-activedescendant` tells a screen reader where the
  // highlight is; a sighted keyboard user needs the list to actually move, and with 164 options in
  // a fixed-height scroller the highlight walks off-screen within a few presses otherwise.
  // Only for KEYBOARD movement. Scrolling on hover puts a different option under a stationary
  // cursor, which fires `mouseenter` again and scrolls again — the list walks under the pointer.
  const scrollOnNextActive = React.useRef(false);
  React.useEffect(() => {
    if (!open || !scrollOnNextActive.current) return;
    scrollOnNextActive.current = false;
    const el = document.getElementById(`${id}-option-${active}`);
    el?.scrollIntoView?.({ block: "nearest" });
  }, [open, active, id]);

  function choose(option: SearchableOption) {
    onChange(option.value);
    close();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      scrollOnNextActive.current = true;
      setActive((current) => {
        if (matches.length === 0) return 0;
        return (current + step + matches.length) % matches.length;
      });
      return;
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      const option = matches[active];
      if (option) choose(option);
      return;
    }
    if (event.key === "Escape" && open) {
      // ESCAPE MUST NOT TAKE THE DRAWER WITH IT (LP-638 review). Radix's DismissableLayer binds
      // its handler on `document` in the CAPTURE phase, so it runs BEFORE this one and dismisses
      // the Sheet — a processor backing out of the type list lost the drawer and the correction in
      // progress.
      //
      // Stopping the event here does not fix that, and a draft of this comment claimed it did:
      // measured, the capture-phase listener still runs, because it has already run by the time
      // any handler on this element is reached. Nothing a child does after the fact can un-run it.
      // The ancestor has to stand down instead, which is what `onOpenChange` is for — the drawer
      // passes `onEscapeKeyDown` to its Sheet and preventDefaults while this list is open.
      //
      // The stop is kept because it is right on its own terms: outside a dismissable ancestor,
      // Escape should close this list and nothing else.
      event.preventDefault();
      event.nativeEvent.stopImmediatePropagation();
      close();
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"
          aria-hidden
        />
        <input
          id={id}
          type="text"
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          aria-controls={`${id}-listbox`}
          aria-autocomplete="list"
          aria-activedescendant={open && matches.length > 0 ? `${id}-option-${active}` : undefined}
          disabled={disabled}
          // The selected label shows while closed; typing replaces it with the query, so the
          // control reads as "what is chosen" at rest and "what am I looking for" while searching.
          value={open ? query : (selected?.label ?? "")}
          placeholder={selected ? selected.label : placeholder}
          onChange={(event) => {
            // Typing opens too — a processor who tabs in and starts typing means to search.
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          // NOT `onFocus` (LP-638 review). The drawer is a Radix Sheet, whose FocusScope focuses
          // the first tabbable node on mount — and this input is it, since everything above is
          // headings and divs. So opening ANY document popped a 164-option listbox over the drawer
          // body, every time. Opening is an explicit act now: click the field, or press a key that
          // means "show me the list".
          //
          // `onMouseDown` rather than `onClick` because after choosing an option focus never left
          // the input (the option's mousedown preventDefaults), so clicking the field fired no
          // focus event and nothing happened — the control was dead until you clicked away first.
          onMouseDown={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="h-9 w-full rounded-md border border-gray-200 bg-white pl-8 pr-8 text-sm text-gray-900 placeholder:text-gray-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
        />
        <ChevronDown
          className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"
          aria-hidden
        />
      </div>

      {open && (
        <div
          id={`${id}-listbox`}
          // biome-ignore lint/a11y/useSemanticElements: a native <select> is exactly what this
          // control replaces — it cannot be typed into, which is the whole point for 164 options.
          // This is the ARIA 1.2 combobox pattern, where the listbox is a container and focus
          // stays on the input, moving the highlight via aria-activedescendant.
          role="listbox"
          tabIndex={-1}
          className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg"
        >
          {matches.length === 0 && (
            <div className="px-3 py-2 text-sm text-gray-500">{emptyMessage}</div>
          )}
          {matches.map((option, index) => {
            // A group header whenever the group changes, so a filtered list still reads as grouped.
            const previous = index > 0 ? matches[index - 1] : undefined;
            const showGroup = option.group && option.group !== previous?.group;
            return (
              <React.Fragment key={option.value}>
                {showGroup && (
                  // `role="presentation"`: a bare div inside a listbox is not a valid child, and
                  // announcing the header as content would interleave it with the options. Sighted
                  // users keep the grouping; assistive tech reads a flat list, which is the
                  // tradeoff this pattern makes without a `role="group"` restructure.
                  <div
                    role="presentation"
                    className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400"
                  >
                    {option.group}
                  </div>
                )}
                <div
                  id={`${id}-option-${index}`}
                  // biome-ignore lint/a11y/useSemanticElements: an <option> only exists inside a
                  // native <select>, which this replaces for the reason above.
                  role="option"
                  // Focus stays on the input and moves the highlight via `aria-activedescendant`,
                  // which is the ARIA combobox pattern — options are never themselves focused, so
                  // they are taken out of the tab order rather than added to it.
                  tabIndex={-1}
                  aria-selected={option.value === value}
                  // onMouseDown, not onClick: mousedown fires before the input's blur, so the
                  // choice lands instead of the list closing out from under the pointer.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    choose(option);
                  }}
                  onMouseEnter={() => setActive(index)}
                  className={cn(
                    "flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm text-gray-900",
                    index === active && "bg-gray-100",
                  )}
                >
                  <span className="truncate">{option.label}</span>
                  {option.value === value && (
                    <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
                  )}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
