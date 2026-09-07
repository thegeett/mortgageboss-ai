"use client";

import { useEffect, useRef } from "react";

import { ExtractionTable } from "@/components/file/documents/extraction-table";
import { AddField } from "@/components/file/documents/reviewer/add-field";
import { ScrutinyMark } from "@/components/file/documents/reviewer/scrutiny-mark";
import { VerdictEditor } from "@/components/file/documents/reviewer/verdict-editor";
import { StatusToken } from "@/components/status-token";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useDocumentDetail } from "@/lib/api/documents";
import { tierInputFor } from "@/lib/confidence";
import { EMPTY_VALUE, type ExtractionField } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * The extracted fields, beside the page they came from (LP-UI-030).
 *
 * Rows reflow to the PANE's width via a container query (`.field-pane` in
 * globals.css), not the window's — a processor drags this from 320px to 720px
 * without the window changing, so a media query would lay out for a viewport the
 * pane no longer fills.
 *
 * Each field shows the text the extraction actually read. That is the whole
 * value of this panel when there is no page image to point at, which measurement
 * says is the case for roughly a quarter of fields.
 */
export function ReviewerFields({
  documentId,
  fields,
  selected,
  hovered,
  onSelect,
  onHover,
  hasBox,
  citationWrong,
  relocated,
  editing,
  onCorrect,
  onReject,
  onRemove,
  onAdd,
  onAddOpenChange,
  onUndo,
  onEdit,
  addableFields,
  onCancelEdit,
  busy,
}: {
  documentId: string | null;
  /**
   * The rows to draw — DERIVED BY THE PAGE, not here (LP-703 review).
   *
   * This component used to call `extractionFields` itself while the page called
   * it again for the keyboard, and the two lists drifted three times. Each time
   * the symptom was a field a processor could SEE but not REACH, or reach but not
   * see: a backend-sensitive field that rendered masked and arrived at the queue
   * as a list, and an ADDED field drawn with no row key, no queue entry and no
   * label, which `editableFieldKey` could never name — the one value a human is
   * personally answerable for was the one row the keyboard could not touch.
   *
   * Both were fixed by making the ARGUMENTS impossible to differ (`sensitiveKeysOf`,
   * `correctionsOf`). This removes the second call instead, which is the only
   * version of the fix that survives the next argument someone adds.
   */
  fields: readonly ExtractionField[];
  selected?: string | null;
  hovered?: string | null;
  onSelect?: (fieldKey: string) => void;
  onHover?: (fieldKey: string | null) => void;
  /** Whether this field's value could be located on the page at all. */
  hasBox?: (fieldKey: string) => boolean;
  /** The extraction cited a page the document does not have. */
  citationWrong?: (fieldKey: string) => boolean;
  /** The text was found on a page other than the one cited. */
  relocated?: (fieldKey: string) => boolean;
  /** The field whose inline editor is open (LP-UI-033), if any. */
  editing?: string | null;
  onCorrect?: (fieldKey: string, value: string) => void;
  onReject?: (fieldKey: string, reason: string) => void;
  /** Take the field out of the snapshot — it is not on this document (LP-703). */
  onRemove?: (fieldKey: string, reason: string) => void;
  /** Supply a field the extraction missed (LP-703). */
  onAdd?: (fieldKey: string, value: string) => void;
  /** Told when the add form opens, so the page can stand the shortcuts down. */
  onAddOpenChange?: (open: boolean) => void;
  /** Withdraw whatever verdict is on this field, putting the model's value back. */
  onUndo?: (fieldKey: string) => void;
  /**
   * Open the verdict editor on this field — the MOUSE path to LP-703's editing.
   *
   * The capability existed from LP-703 and `setEditing` was called only from the
   * `E` and `R` key handlers, so a processor using a mouse could select a field
   * and read it and change nothing.
   */
  onEdit?: (fieldKey: string) => void;
  /** Field names this document type declares and the extraction does not carry. */
  addableFields?: readonly string[];
  onCancelEdit?: () => void;
  busy?: boolean;
}) {
  const { data, isPending, isError } = useDocumentDetail(documentId);

  // BRING THE SELECTED ROW INTO VIEW. The fields pane scrolls
  // (`ReviewerShell`'s section is `overflow-y-auto`), and selecting a field only
  // changed a background colour — so clicking a box on the page highlighted a
  // row that could be well below the fold, and the ticket's headline
  // interaction appeared to do nothing in the direction it was built for.
  //
  // `block: "nearest"` so a row already on screen does not move: clicking a row
  // directly must not scroll the list out from under the pointer.
  //
  // KEYED ON THE ROW BEING THERE, not on the selection alone — the same correction
  // the box overlay needed, and this side is where that pattern was copied FROM.
  // Selection arrives from the document as well as from here, and the two sides
  // load on separate queries: a processor who clicks a box while this pane is
  // still a skeleton set `selected` in a commit where no row is rendered and the
  // ref is null. The rows arrive in a later commit with the selection unchanged,
  // so nothing ran again and the row stayed below the fold — which is the exact
  // symptom this effect was written to remove, in the direction it was written for.
  const selectedRow = useRef<HTMLLIElement | null>(null);
  const rowOnScreen =
    !isPending && !isError && selected && fields.some((f) => f.key === selected) ? selected : null;
  useEffect(() => {
    if (!rowOnScreen) return;
    selectedRow.current?.scrollIntoView({ block: "nearest" });
  }, [rowOnScreen]);

  if (!documentId) {
    return <Note>No document selected.</Note>;
  }
  if (isPending) {
    return (
      <div className="space-y-2 p-3" aria-busy>
        <output className="sr-only">Loading the extracted fields</output>
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-5 w-3/4" />
      </div>
    );
  }
  if (isError || !data) {
    return <Note>Couldn&rsquo;t load this document&rsquo;s fields.</Note>;
  }

  const scrutiny = data.field_scrutiny ?? {};

  return (
    // One provider for the pane rather than one per row — forty providers is forty
    // subscriptions to the same delay.
    <TooltipProvider delayDuration={150}>
      <div className="field-pane p-3">
        <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pb-2">
          <h3 className="text-label uppercase text-muted-foreground">Extracted fields</h3>
          <StatusToken meta={resolveStatus(DOCUMENT_STATUS, data.status)} className="text-xs" />
        </header>

        {fields.length === 0 ? (
          <Note>
            Nothing has been extracted from this document yet. That is not the same as a document
            with no values — an extraction may still be running, or this type may be recorded rather
            than read.
          </Note>
        ) : (
          <ul className="space-y-2">
            {fields.map((field) => (
              // THE WHOLE ROW IS THE CONTROL, and until now only the label was. The
              // comment here has claimed "the whole row is the control rather than a
              // small affordance inside it" since LP-UI-030, while the click handler
              // sat on the label button alone — so clicking a value, a snippet or the
              // space beside them did nothing, and a processor reading a row had to go
              // back and hit the one word at its left edge to see the box.
              //
              // On the LI rather than a wrapping button, because the row already
              // contains buttons (Undo, the verdict editor, a table disclosure) and
              // nesting them inside a button is invalid. A click on one of those
              // bubbles here and also selects, which is what someone acting on a row
              // means anyway.
              //
              // THE KEYBOARD REACHES THIS ROW THROUGH THE LABEL BUTTON, whose
              // activation the browser delivers as a click and which therefore lands
              // on the handler here — so the row is reachable without a pointer and a
              // key handler on the LI would fire a SECOND time for every Enter. That
              // is the whole justification for the suppression below, and it is held
              // by `reviewer-fields-scroll.test.tsx`: the label is a real button, and
              // activating it selects.
              //
              // ONE HANDLER, AND IT IS THIS ONE. The button carried its own `onClick`
              // calling the same thing, which fired `onSelect` TWICE for every label
              // activation — harmless only because selection happens to be idempotent
              // — and could be deleted with the whole suite green, because this
              // handler caught the click either way. A second copy of a rule that
              // nothing can hold is the shape that drifts.
              // biome-ignore lint/a11y/useKeyWithClickEvents: the label button is the keyboard path — see above
              <li
                key={field.key}
                ref={field.key === selected ? selectedRow : undefined}
                className={cn(
                  "field-row cursor-pointer rounded-sm border-b border-border px-1 pb-2 last:border-b-0",
                  field.key === selected && "bg-primary/10",
                  field.key === hovered && field.key !== selected && "bg-muted",
                )}
                onClick={() => onSelect?.(field.key)}
                onMouseEnter={() => onHover?.(field.key)}
                onMouseLeave={() => onHover?.(null)}
              >
                <button
                  type="button"
                  className="text-left text-xs text-muted-foreground"
                  onFocus={() => onHover?.(field.key)}
                  onBlur={() => onHover?.(null)}
                >
                  {field.label}
                </button>
                <span className="min-w-0">
                  {/* A list or a nested record — the count IS the value line, and
                    it opens the rows. Without this the row showed
                    `[object Object]` for every one of the 78 list keys the
                    extraction contracts declare. The label is not repeated: the
                    button above is already this field's name. */}
                  {field.kind === "scalar" ? (
                    <>
                      <span className="block break-words text-sm font-medium text-foreground">
                        {field.value || EMPTY_VALUE}
                      </span>
                      {/* WHAT THE MODEL SAID, kept visible beside the correction.
                        The extraction is untouched by design, so this is the row
                        that answers "what did the model actually say?" — the
                        question every accuracy investigation starts from. */}
                      {field.replacedValue ? (
                        <span className="mt-0.5 block break-words text-xs text-muted-foreground">
                          The extraction read {field.replacedValue}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <ExtractionTable
                      summary={field.value}
                      columns={field.columns}
                      rows={field.rows}
                    />
                  )}
                  {/* The text the value was read from. On a document with no page
                    image this is the only provenance a processor has, so it is
                    shown rather than hidden behind a hover. */}
                  {field.source?.snippet ? (
                    <span className="mt-0.5 block break-words text-xs text-muted-foreground">
                      &ldquo;{field.source.snippet}&rdquo;
                      {field.source.page ? ` · p.${field.source.page}` : ""}
                    </span>
                  ) : null}

                  {/* A list has no single value to accept or correct, so it carries
                      no mark and opens no editor (LP-702); editing rows is LP-703's
                      subject.

                      THE EMPTY-VALUE RULE APPLIES TO THE MARK ALONE, and used to
                      gate this whole group by sitting on the outside of it. A mark
                      on a field with no value would be telling a processor to go and
                      read a dash — that argument is about the MARK. Applied to Edit
                      and Undo it made the mouse and the keyboard disagree in exactly
                      the case LP-711 says they cannot: `editableFieldKey` asks only
                      whether a field is scalar, so `E` opens the editor on a field
                      the model returned empty while no Edit control was drawn for
                      it, and that is the one field a processor most needs to supply
                      — `AddField` cannot offer it either, because it is already in
                      the extraction. Undo went the same way, so a verdict recorded
                      on an empty field by keystroke could not be withdrawn from the
                      screen at all, which is the LP-703 finding again. */}
                  {field.kind === "scalar" ? (
                    <span className="flex flex-wrap items-center gap-x-2">
                      {field.value && field.value !== EMPTY_VALUE ? (
                        <ScrutinyMark input={tierInputFor(field.confidence, scrutiny[field.key])} />
                      ) : null}
                      {/* UNDO IS REACHABLE, which it was not until LP-703.
                        `useRevertFieldReview` existed from LP-UI-033 and no
                        component called it, so every decision — including one made
                        by a mis-key — was permanent from the screen. A removal and
                        an addition make that worse, because they change what the
                        checks compute from. */}
                      {/* THE MOUSE PATH TO EDITING, which did not exist (LP-711).
                        LP-703 built correcting a value, removing a field and adding
                        one, all undoable and all reaching the rule engine — and
                        `setEditing` was reachable ONLY from the `E` and `R` keys.
                        A processor working with a mouse could select a field and
                        see its box, and could not change anything at all; the whole
                        feature was behind a shortcut discoverable only by opening
                        the `?` sheet.

                        On the SELECTED row rather than every row: a control on
                        forty rows at once is the chrome LP-UI-032 spent a ticket
                        removing. */}
                      {onEdit && field.key === selected && editing !== field.key ? (
                        <button
                          type="button"
                          className="rounded text-xs text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => onEdit(field.key)}
                          disabled={busy}
                        >
                          Edit
                        </button>
                      ) : null}
                      {onUndo && scrutiny[field.key]?.verdict ? (
                        <button
                          type="button"
                          className="rounded text-xs text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => onUndo(field.key)}
                          disabled={busy}
                        >
                          Undo
                        </button>
                      ) : null}
                    </span>
                  ) : null}

                  {editing === field.key && field.kind === "scalar" ? (
                    <VerdictEditor
                      fieldLabel={field.label}
                      currentValue={field.value}
                      onCorrect={(value) => onCorrect?.(field.key, value)}
                      onReject={(reason) => onReject?.(field.key, reason)}
                      onRemove={(reason) => onRemove?.(field.key, reason)}
                      onCancel={() => onCancelEdit?.()}
                      busy={busy}
                    />
                  ) : null}

                  <CitationNote
                    cited={Boolean(field.source?.snippet)}
                    citationWrong={citationWrong?.(field.key) ?? false}
                    relocated={relocated?.(field.key) ?? false}
                    located={hasBox ? hasBox(field.key) : true}
                  />
                </span>
              </li>
            ))}
          </ul>
        )}

        {onAdd ? (
          <AddField
            fields={addableFields ?? []}
            onAdd={onAdd}
            busy={busy}
            onOpenChange={onAddOpenChange}
          />
        ) : null}
      </div>
    </TooltipProvider>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="max-w-prose p-3 text-sm text-muted-foreground">{children}</p>;
}

/**
 * What the page can and cannot show for one field.
 *
 * Its own component because these three sentences are the honest part of the
 * feature and each of them is a claim about the extraction, not about the UI. A
 * citation naming a page the document does not have is shown as exactly that —
 * silently rendering a better page would turn a provenance trail into a guess.
 */
export function CitationNote({
  cited,
  citationWrong,
  relocated,
  located,
}: {
  /** The extraction quoted text for this field. Without one there is no claim to check. */
  cited: boolean;
  /** The cited page number is beyond the document's length. */
  citationWrong: boolean;
  /** The quoted text was found on a page other than the one cited. */
  relocated: boolean;
  /** The quoted text was located somewhere in the document. */
  located: boolean;
}) {
  // A field the extraction never filled has nothing to locate, and telling the
  // processor it could not be found reads as a lookup failure rather than an
  // empty field.
  if (!cited) return null;

  if (citationWrong) {
    return (
      <span className="mt-0.5 block text-xs text-warning">
        The extraction cited a page this document does not have
        {relocated ? " — the text is shown where it actually appears." : "."}
      </span>
    );
  }
  if (relocated) {
    return (
      <span className="mt-0.5 block text-xs text-warning">
        Found on a different page than the one cited.
      </span>
    );
  }
  // No box is ORDINARY — roughly a quarter of real fields. Saying so beats a
  // field that simply never highlights, leaving the processor wondering whether
  // the click registered.
  if (!located) {
    return (
      <span className="mt-0.5 block text-xs text-muted-foreground">
        Not locatable on the page — read the quoted text above.
      </span>
    );
  }
  return null;
}
