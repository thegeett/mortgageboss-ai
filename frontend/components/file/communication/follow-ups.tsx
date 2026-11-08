"use client";

/**
 * LP-1014 — automatic follow-ups on screen (LP-1013's API).
 *
 * - `SendFollowUpBox`: "Follow up if no reply" above the draft pane's button bar, where Send is.
 * - `FollowUpBar`: under the header of a sent email — its status, what it waits for, the next
 *   reminder, how many went, and the buttons its state allows.
 * - `FollowUpPill`: the small status on the email's row in the message list.
 * - `FollowUpsList`: every follow-up on the file, full width above the two panes.
 *
 * ONE SET OF RULES FOR THE BUTTONS (`FollowUpActions`), used by the bar and by the list, so the two
 * cannot offer different things for the same email. No dialog: Edit and Start open their three
 * fields inline.
 */
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type FollowUpAction,
  type FollowUpSettings,
  useFollowUpAction,
  useFollowUps,
} from "@/lib/api/follow-ups";
import { getErrorMessage } from "@/lib/errors/api-error";
import {
  PILL_CLASSES,
  browserTimeZone,
  currentTime,
  firstReminderAt,
  followUpPill,
  followUpState,
  formatWhen,
  sentCount,
} from "@/lib/follow-ups";
import type { FollowUp, FollowUpRow, MessageDetail } from "@/lib/types/communication";
import { cn } from "@/lib/utils";
import { useState } from "react";

/** Real buttons, at least 36px high (the brief), in the app's outline style. */
const ACTION = "min-h-9";

export const DEFAULT_SETTINGS = (): FollowUpSettings => ({
  interval_days: 3,
  max_auto: 2,
  time: currentTime(),
});

// --------------------------------------------------------------------------------------------- //
// The three fields
// --------------------------------------------------------------------------------------------- //
/**
 * A whole number between `min` and `max` that can be cleared and retyped (review finding 6).
 *
 * WHAT SHE TYPES IS HELD AS TEXT, and only a value in range is passed up. Correcting on every
 * keystroke made the field unclearable: Backspace on "3" snapped back to 3, and typing 7 then gave
 * "37", silently 30. Out of range or empty, the field is put right when she leaves it.
 */
function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const [shown, setShown] = useState(value);
  if (value !== shown) {
    // Changed from outside (Edit opening, a reset): show the new value.
    setShown(value);
    setText(String(value));
  }
  return (
    <Input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      aria-label={label}
      className="h-9 w-16"
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        const number = Number(event.target.value);
        if (
          event.target.value !== "" &&
          Number.isInteger(number) &&
          number >= min &&
          number <= max
        ) {
          setShown(number);
          onChange(number);
        }
      }}
      onBlur={() => {
        const number = Number.parseInt(text, 10);
        const fixed = Number.isNaN(number) ? value : Math.min(max, Math.max(min, number));
        setText(String(fixed));
        if (fixed !== value) {
          setShown(fixed);
          onChange(fixed);
        }
      }}
    />
  );
}

export function FollowUpFields({
  value,
  onChange,
  tz,
}: {
  value: FollowUpSettings;
  onChange: (next: FollowUpSettings) => void;
  tz: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-foreground">
      <span>Every</span>
      <NumberField
        label="Days between reminders"
        value={value.interval_days}
        min={1}
        max={30}
        onChange={(interval_days) => onChange({ ...value, interval_days })}
      />
      <span>days, up to</span>
      {/* AT LEAST ONE (review finding 5): none would read "No reply" the moment it is sent. */}
      <NumberField
        label="Number of reminders"
        value={value.max_auto}
        min={1}
        max={10}
        onChange={(max_auto) => onChange({ ...value, max_auto })}
      />
      <span>reminders, at</span>
      <Input
        type="time"
        aria-label="Time of day"
        className="h-9 w-28"
        value={value.time}
        onChange={(event) => onChange({ ...value, time: event.target.value || value.time })}
      />
      <span className="text-muted-foreground">{tz}</span>
    </div>
  );
}

// --------------------------------------------------------------------------------------------- //
// The box above Send
// --------------------------------------------------------------------------------------------- //
export function SendFollowUpBox({
  enabled,
  onEnabled,
  settings,
  onSettings,
  now = new Date(),
}: {
  enabled: boolean;
  onEnabled: (on: boolean) => void;
  settings: FollowUpSettings;
  onSettings: (next: FollowUpSettings) => void;
  now?: Date;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border px-3 py-2">
      <label className="flex min-h-9 items-center gap-2 text-sm font-medium text-foreground">
        <input
          type="checkbox"
          className="accent-primary"
          checked={enabled}
          onChange={(event) => onEnabled(event.target.checked)}
        />
        Follow up if no reply
      </label>
      {enabled ? (
        <>
          <FollowUpFields value={settings} onChange={onSettings} tz={browserTimeZone()} />
          <p className="text-xs text-muted-foreground">
            First reminder:{" "}
            {formatWhen(firstReminderAt(now, settings.interval_days, settings.time))}
          </p>
        </>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------------------------------------- //
// The pill
// --------------------------------------------------------------------------------------------- //
export function FollowUpPill({
  followUp,
  senderActive = true,
  className,
}: {
  followUp: FollowUp;
  senderActive?: boolean;
  className?: string;
}) {
  const pill = followUpPill(followUp, senderActive);
  if (!pill) return null;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        PILL_CLASSES[pill.tone],
        className,
      )}
    >
      {pill.label}
    </span>
  );
}

// --------------------------------------------------------------------------------------------- //
// The buttons, by state — one set of rules for the bar and the list
// --------------------------------------------------------------------------------------------- //
/** The state in a processor's words. */
export function stateSentence(state: ReturnType<typeof followUpState>, senderName: string | null) {
  switch (state) {
    case "on":
      return "On";
    case "paused":
      return "Paused — they replied";
    case "no_reply":
      return "No reply";
    case "finished":
      return "Everything arrived";
    case "stopped_sender_inactive":
      return `Stopped — ${senderName ?? "the sender"}'s account was deactivated`;
    case "stopped_failed":
      return "Stopped — the email failed";
    case "stopped_blocked":
      return "Stopped — address blocked (bounce or complaint)";
    case "stopped":
      return "Stopped";
    default:
      return "Off";
  }
}

function settingsOf(followUp: FollowUp): FollowUpSettings {
  return {
    interval_days: followUp.interval_days,
    max_auto: followUp.max_auto,
    time: followUp.time ?? currentTime(),
  };
}

export function FollowUpActions({
  fileId,
  communicationId,
  followUp,
  senderActive = true,
  emailFailed = false,
  recipientSuppressed = false,
}: {
  fileId: string;
  communicationId: string;
  followUp: FollowUp;
  senderActive?: boolean;
  emailFailed?: boolean;
  recipientSuppressed?: boolean;
}) {
  const action = useFollowUpAction(fileId, communicationId);
  const [form, setForm] = useState<"edit" | "start" | null>(null);
  const [settings, setSettings] = useState<FollowUpSettings>(() => settingsOf(followUp));
  // A failed original (`stopped_failed`) or a blocked address (`stopped_blocked`) offers nothing:
  // Start would be refused, or would never send.
  const state = followUpState(followUp, senderActive, emailFailed, recipientSuppressed);

  function run(next: FollowUpAction) {
    action.mutate(next, { onSuccess: () => setForm(null) });
  }

  function open(mode: "edit" | "start") {
    setSettings(mode === "edit" ? settingsOf(followUp) : DEFAULT_SETTINGS());
    setForm(mode);
  }

  const busy = action.isPending;
  const button = (
    label: string,
    onClick: () => void,
    variant: "outline" | "default" = "outline",
  ) => (
    <Button
      key={label}
      type="button"
      variant={variant}
      className={ACTION}
      disabled={busy}
      onClick={onClick}
    >
      {label}
    </Button>
  );

  const buttons: React.ReactNode[] = [];
  if (state === "on") {
    buttons.push(button("Edit", () => open("edit")));
    buttons.push(button("Send now", () => run({ kind: "send-now" })));
    buttons.push(button("Stop", () => run({ kind: "stop" })));
  } else if (state === "paused") {
    buttons.push(button("Resume", () => run({ kind: "resume" }), "default"));
    buttons.push(button("Send now", () => run({ kind: "send-now" })));
    buttons.push(button("Stop", () => run({ kind: "stop" })));
  } else if (state === "no_reply") {
    buttons.push(button("Send now", () => run({ kind: "send-now" }), "default"));
    // LP-1015 — so the red row can be cleared without sending anything.
    buttons.push(button("Stop", () => run({ kind: "stop" })));
  } else if (state === "stopped" || state === "off") {
    buttons.push(button("Start follow-ups", () => open("start")));
  }

  if (buttons.length === 0) return null;
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: only stops a row's click from opening the email
    <div className="flex flex-col gap-2" onClick={(event) => event.stopPropagation()}>
      {form ? (
        <div className="flex flex-col gap-2">
          <FollowUpFields
            value={settings}
            onChange={setSettings}
            tz={form === "edit" ? (followUp.tz ?? browserTimeZone()) : browserTimeZone()}
          />
          <div className="flex flex-wrap gap-2">
            {button(
              form === "edit" ? "Save" : "Start",
              () =>
                run(
                  form === "edit"
                    ? { kind: "edit", settings }
                    : { kind: "start", settings, tz: browserTimeZone() },
                ),
              "default",
            )}
            {button("Cancel", () => setForm(null))}
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">{buttons}</div>
      )}
      {action.isError ? (
        <p className="text-sm text-danger">{getErrorMessage(action.error)}</p>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------------------------------------- //
// The bar on a sent email
// --------------------------------------------------------------------------------------------- //
/** When the next automatic reminder goes, in the follow-up's own zone; only while one will. */
function nextReminder(followUp: FollowUp, state: ReturnType<typeof followUpState>): string | null {
  if (state === "on" && followUp.next_reminder_at) {
    return formatWhen(followUp.next_reminder_at, followUp.tz);
  }
  return null;
}

export function FollowUpBar({ fileId, message }: { fileId: string; message: MessageDetail }) {
  const followUp = message.follow_up;
  // Who sent it and whether that account is active: only the list carries it.
  const row = useFollowUps(fileId).data?.find((r) => r.communication_id === message.id);
  if (!followUp) return null;
  const senderActive = row?.sender_active ?? true;
  const emailFailed = message.status === "failed";
  const recipientSuppressed = row?.recipient_suppressed ?? false;
  const state = followUpState(followUp, senderActive, emailFailed, recipientSuppressed);
  const next = nextReminder(followUp, state);
  return (
    <section
      aria-label="Follow-up"
      className="flex flex-col gap-2 rounded-lg border border-border px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-foreground">Follow-up</span>
        {state === "off" ? null : <FollowUpPill followUp={followUp} senderActive={senderActive} />}
        <span className="text-foreground">{stateSentence(state, row?.sender_name ?? null)}</span>
      </div>
      {state === "off" ? null : (
        <dl className="grid gap-0.5 text-xs text-muted-foreground">
          <div className="flex gap-2">
            <dt className="font-medium text-foreground">Waiting for</dt>
            <dd>{followUp.waiting_for.join(", ")}</dd>
          </div>
          {next ? (
            <div className="flex gap-2">
              <dt className="font-medium text-foreground">Next</dt>
              <dd>{next}</dd>
            </div>
          ) : null}
          <div className="flex gap-2">
            <dt className="font-medium text-foreground">Sent</dt>
            <dd>{sentCount(followUp)}</dd>
          </div>
        </dl>
      )}
      <FollowUpActions
        key={`${message.id}-${followUp.status}`}
        fileId={fileId}
        communicationId={message.id}
        followUp={followUp}
        senderActive={senderActive}
        emailFailed={emailFailed}
        recipientSuppressed={recipientSuppressed}
      />
    </section>
  );
}

// --------------------------------------------------------------------------------------------- //
// The Follow-ups list, above the panes
// --------------------------------------------------------------------------------------------- //
/** "No reply" first, then the rest in the server's order (newest first). */
export function orderRows(rows: FollowUpRow[]): FollowUpRow[] {
  const noReply = rows.filter((r) => followUpState(r.follow_up, r.sender_active) === "no_reply");
  const rest = rows.filter((r) => followUpState(r.follow_up, r.sender_active) !== "no_reply");
  return [...noReply, ...rest];
}

export function FollowUpsList({
  fileId,
  selectedId,
  onOpen,
}: {
  fileId: string;
  selectedId: string | null;
  onOpen: (communicationId: string) => void;
}) {
  const rows = useFollowUps(fileId).data ?? [];
  if (rows.length === 0) return null;
  return (
    <section aria-label="Follow-ups" className="flex flex-col gap-2">
      <h2 className="text-base font-semibold text-foreground">Follow-ups</h2>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="border-b border-border text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-3 py-2 font-medium">Waiting for</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Next / sent</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {orderRows(rows).map((row) => {
              const emailFailed = row.email_status === "failed";
              const state = followUpState(
                row.follow_up,
                row.sender_active,
                emailFailed,
                row.recipient_suppressed,
              );
              const noReply = state === "no_reply";
              const next = nextReminder(row.follow_up, state);
              return (
                // biome-ignore lint/a11y/useKeyWithClickEvents: the subject below is the row's keyboard way in (a real button); the row click is a larger mouse target for the same action
                <tr
                  key={row.communication_id}
                  aria-current={row.communication_id === selectedId ? "true" : undefined}
                  onClick={() => onOpen(row.communication_id)}
                  className={cn(
                    "cursor-pointer border-b border-border align-top last:border-b-0 hover:bg-muted/50",
                    noReply && "bg-danger/5 text-danger",
                    row.communication_id === selectedId && "bg-primary/5",
                  )}
                >
                  <td className="px-3 py-2">
                    {/* The row's keyboard way in: a real button, not only a clickable row. */}
                    <button
                      type="button"
                      className={cn(
                        "min-h-9 text-left font-medium hover:underline",
                        noReply ? "text-danger" : "text-foreground",
                      )}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpen(row.communication_id);
                      }}
                    >
                      {row.subject ?? "(no subject)"}
                    </button>
                    <p className={cn("text-xs", noReply ? "text-danger" : "text-muted-foreground")}>
                      To {row.recipient ?? "nobody"} · by {row.sender_name ?? "unknown"}
                    </p>
                  </td>
                  <td className="px-3 py-2">{row.follow_up.waiting_for.join(", ")}</td>
                  <td className="px-3 py-2">
                    <FollowUpPill followUp={row.follow_up} senderActive={row.sender_active} />
                    {state === "stopped_sender_inactive" ||
                    state === "stopped_failed" ||
                    state === "stopped_blocked" ||
                    state === "paused" ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {stateSentence(state, row.sender_name)}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {next ? <p>Next {next}</p> : null}
                    <p className={noReply ? undefined : "text-muted-foreground"}>
                      {sentCount(row.follow_up)}
                    </p>
                  </td>
                  <td className="px-3 py-2">
                    <FollowUpActions
                      key={`${row.communication_id}-${row.follow_up.status}`}
                      fileId={fileId}
                      communicationId={row.communication_id}
                      followUp={row.follow_up}
                      senderActive={row.sender_active}
                      emailFailed={emailFailed}
                      recipientSuppressed={row.recipient_suppressed}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
