// @vitest-environment jsdom
/**
 * LP-1014 — follow-ups on screen: the state rules, the box above Send, the bar on a sent email,
 * and the Follow-ups list above the panes.
 */
import {
  FollowUpBar,
  FollowUpsList,
  SendFollowUpBox,
} from "@/components/file/communication/follow-ups";
import { firstReminderAt, followUpPill, followUpState, formatWhen } from "@/lib/follow-ups";
import type { FollowUp, FollowUpRow, MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockMutate = vi.fn();
const mockFollowUps = vi.fn((): { data: FollowUpRow[] } => ({ data: [] }));
vi.mock("@/lib/api/follow-ups", () => ({
  useFollowUps: () => mockFollowUps(),
  useFollowUpAction: () => ({ mutate: mockMutate, isPending: false, isError: false }),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  mockFollowUps.mockReturnValue({ data: [] });
});

function followUp(overrides: Partial<FollowUp> = {}): FollowUp {
  return {
    status: "on",
    interval_days: 3,
    max_auto: 2,
    auto_sent: 0,
    clock_at: "2026-11-06T14:00:00Z",
    paused_at: null,
    // Monday 9 November 2026, 09:30 in New York (EST, UTC-5).
    next_reminder_at: "2026-11-09T14:30:00Z",
    time: "09:30",
    tz: "America/New_York",
    waiting_for: ["Bank statements", "W-2"],
    ...overrides,
  };
}

function row(id: string, overrides: Partial<FollowUp> = {}, extra: Partial<FollowUpRow> = {}) {
  return {
    communication_id: id,
    subject: `Subject ${id}`,
    recipient: "jane@example.test",
    sender_name: "Priya Desai",
    sender_active: true,
    email_status: "sent",
    recipient_suppressed: false,
    follow_up: followUp(overrides),
    ...extra,
  } satisfies FollowUpRow;
}

function message(fu: FollowUp): MessageDetail {
  return { id: "m1", follow_up: fu } as unknown as MessageDetail;
}

// --------------------------------------------------------------------------------------------- //
describe("follow-up state and pill", () => {
  it.each([
    [{ status: "on" as const, auto_sent: 1 }, true, "on", "Follow-up · Mon", "success"],
    [{ status: "paused" as const }, true, "paused", "Paused", "warning"],
    [{ status: "on" as const, auto_sent: 2 }, true, "no_reply", "No reply", "danger"],
    [{ status: "finished" as const }, true, "finished", "Finished", "neutral"],
    [{ status: "stopped" as const }, true, "stopped", "Stopped", "neutral"],
    [{ status: "stopped" as const }, false, "stopped_sender_inactive", "Stopped", "neutral"],
  ])("%o (sender active %s) is %s, pill %s", (over, active, state, label, tone) => {
    expect(followUpState(followUp(over), active)).toBe(state);
    expect(followUpPill(followUp(over), active)).toEqual({ label, tone });
  });

  it("has no pill when off", () => {
    expect(followUpPill(followUp({ status: "off" }))).toBeNull();
  });

  it("reads the weekday in the follow-up's own zone, not the browser's", () => {
    // 03:00 UTC Tuesday is still Monday evening in Los Angeles.
    const late = followUp({ next_reminder_at: "2026-11-10T03:00:00Z", tz: "America/Los_Angeles" });
    expect(followUpPill(late)?.label).toBe("Follow-up · Mon");
    expect(formatWhen("2026-11-10T03:00:00Z", "America/Los_Angeles")).toBe("Mon, Nov 9 at 7:00 PM");
  });
});

describe("first reminder", () => {
  it.each([
    ["Tuesday + 3 → Friday", new Date(2026, 9, 13, 10, 0), "2026-10-16"],
    ["Wednesday + 3 → Saturday → Monday", new Date(2026, 9, 14, 10, 0), "2026-10-19"],
    ["Thursday + 3 → Sunday → Monday", new Date(2026, 9, 15, 10, 0), "2026-10-19"],
  ])("%s", (_, now, day) => {
    const due = firstReminderAt(now, 3, "09:30");
    const local = `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, "0")}-${String(due.getDate()).padStart(2, "0")}`;
    expect(local).toBe(day);
    expect([due.getHours(), due.getMinutes()]).toEqual([9, 30]);
  });
});

// --------------------------------------------------------------------------------------------- //
describe("the box above Send", () => {
  const settings = { interval_days: 3, max_auto: 2, time: "09:30" };

  it("is unticked, and shows no fields, until ticked", () => {
    const onEnabled = vi.fn();
    render(
      <SendFollowUpBox
        enabled={false}
        onEnabled={onEnabled}
        settings={settings}
        onSettings={vi.fn()}
      />,
    );
    const box = screen.getByRole("checkbox", { name: "Follow up if no reply" });
    expect((box as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByLabelText("Days between reminders")).toBeNull();
    fireEvent.click(box);
    expect(onEnabled).toHaveBeenCalledWith(true);
  });

  it("when ticked: the three fields, the zone, and the first reminder's date", () => {
    render(
      <SendFollowUpBox
        enabled
        onEnabled={vi.fn()}
        settings={settings}
        onSettings={vi.fn()}
        now={new Date(2026, 9, 14, 10, 0)} // a Wednesday
      />,
    );
    expect((screen.getByLabelText("Days between reminders") as HTMLInputElement).value).toBe("3");
    expect((screen.getByLabelText("Number of reminders") as HTMLInputElement).value).toBe("2");
    expect((screen.getByLabelText("Time of day") as HTMLInputElement).value).toBe("09:30");
    expect(screen.getByText(Intl.DateTimeFormat().resolvedOptions().timeZone)).toBeTruthy();
    expect(screen.getByText("First reminder: Mon, Oct 19 at 9:30 AM")).toBeTruthy();
  });

  it("changing a field reports the new settings", () => {
    const onSettings = vi.fn();
    render(
      <SendFollowUpBox enabled onEnabled={vi.fn()} settings={settings} onSettings={onSettings} />,
    );
    fireEvent.change(screen.getByLabelText("Days between reminders"), { target: { value: "5" } });
    expect(onSettings).toHaveBeenCalledWith({ ...settings, interval_days: 5 });
  });
});

// --------------------------------------------------------------------------------------------- //
function buttonNames(): string[] {
  return screen.queryAllByRole("button").map((b) => b.textContent ?? "");
}

describe("the bar on a sent email", () => {
  it("On: status, waiting for, next in its zone, the count, and Edit / Send now / Stop", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ auto_sent: 1 }))} />);
    const bar = screen.getByRole("region", { name: "Follow-up" });
    expect(within(bar).getByText("On")).toBeTruthy();
    expect(within(bar).getByText("Bank statements, W-2")).toBeTruthy();
    expect(within(bar).getByText("Mon, Nov 9 at 9:30 AM")).toBeTruthy();
    expect(within(bar).getByText("1 of 2 sent")).toBeTruthy();
    expect(buttonNames()).toEqual(["Edit", "Send now", "Stop"]);
  });

  it("buttons are real, at least 36px high", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp())} />);
    for (const button of screen.getAllByRole("button")) {
      expect(button.tagName).toBe("BUTTON");
      expect(button.className).toContain("min-h-9");
    }
  });

  it("Edit opens the three fields inline; Save sends a PATCH with them", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp())} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Days between reminders"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Time of day"), { target: { value: "08:15" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mockMutate.mock.calls[0]?.[0]).toEqual({
      kind: "edit",
      settings: { interval_days: 5, max_auto: 2, time: "08:15" },
    });
  });

  it.each([
    ["Send now", { kind: "send-now" }],
    ["Stop", { kind: "stop" }],
  ])("%s calls its endpoint", (name, call) => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp())} />);
    fireEvent.click(screen.getByRole("button", { name }));
    expect(mockMutate.mock.calls[0]?.[0]).toEqual(call);
  });

  it("Paused: says they replied; Resume, Send now, Stop", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ status: "paused" }))} />);
    expect(screen.getByText("Paused — they replied")).toBeTruthy();
    expect(buttonNames()).toEqual(["Resume", "Send now", "Stop"]);
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(mockMutate.mock.calls[0]?.[0]).toEqual({ kind: "resume" });
  });

  it("No reply: Send now and Stop (LP-1015), and no next date", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ auto_sent: 2 }))} />);
    expect(screen.getAllByText("No reply").length).toBeGreaterThan(0);
    expect(buttonNames()).toEqual(["Send now", "Stop"]);
    expect(screen.queryByText("Mon, Nov 9 at 9:30 AM")).toBeNull();
  });

  it("Finished: everything arrived, no buttons", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ status: "finished" }))} />);
    expect(screen.getByText("Everything arrived")).toBeTruthy();
    expect(buttonNames()).toEqual([]);
  });

  it("Stopped with the sender deactivated: says so, no buttons", () => {
    mockFollowUps.mockReturnValue({
      data: [row("m1", { status: "stopped" }, { sender_active: false })],
    });
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ status: "stopped" }))} />);
    expect(screen.getByText("Stopped — Priya Desai's account was deactivated")).toBeTruthy();
    expect(buttonNames()).toEqual([]);
  });

  it.each(["stopped", "off"] as const)(
    "%s: Start follow-ups opens the fields; Start posts them with the browser's zone",
    (status) => {
      render(<FollowUpBar fileId="LF-1" message={message(followUp({ status }))} />);
      expect(buttonNames()).toEqual(["Start follow-ups"]);
      fireEvent.click(screen.getByRole("button", { name: "Start follow-ups" }));
      fireEvent.change(screen.getByLabelText("Time of day"), { target: { value: "10:00" } });
      fireEvent.click(screen.getByRole("button", { name: "Start" }));
      expect(mockMutate.mock.calls[0]?.[0]).toEqual({
        kind: "start",
        settings: { interval_days: 3, max_auto: 2, time: "10:00" },
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
    },
  );
});

// --------------------------------------------------------------------------------------------- //
describe("the Follow-ups list", () => {
  it("is absent when the file has none", () => {
    const { container } = render(
      <FollowUpsList fileId="LF-1" selectedId={null} onOpen={vi.fn()} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("puts No reply first, in the danger colour, then the rest in the server's order", () => {
    mockFollowUps.mockReturnValue({
      data: [row("newest"), row("paused", { status: "paused" }), row("no-reply", { auto_sent: 2 })],
    });
    render(<FollowUpsList fileId="LF-1" selectedId={null} onOpen={vi.fn()} />);
    const rows = screen.getAllByRole("row").slice(1); // the header row
    expect(rows.map((r) => within(r).getAllByRole("button")[0]?.textContent)).toEqual([
      "Subject no-reply",
      "Subject newest",
      "Subject paused",
    ]);
    expect(rows[0]?.className).toContain("text-danger");
    expect(rows[1]?.className).not.toContain("text-danger");
    expect(
      within(rows[0] as HTMLElement).getByText("To jane@example.test · by Priya Desai"),
    ).toBeTruthy();
  });

  it("opens the email when a row or its subject is clicked, not when an action is", () => {
    mockFollowUps.mockReturnValue({ data: [row("a")] });
    const onOpen = vi.fn();
    render(<FollowUpsList fileId="LF-1" selectedId={null} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Subject a" }));
    expect(onOpen).toHaveBeenCalledWith("a");
    fireEvent.click(screen.getByText("Bank statements, W-2"));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});

// --------------------------------------------------------------------------------------------- //
describe("LP-1014 review fixes", () => {
  const settings = { interval_days: 3, max_auto: 2, time: "09:30" };

  /** A parent that keeps what the box reports, as `DraftPane` does; `onSettings` records it. */
  function box(onSettings = vi.fn()) {
    function Parent() {
      const [value, setValue] = useState(settings);
      return (
        <SendFollowUpBox
          enabled
          onEnabled={vi.fn()}
          settings={value}
          onSettings={(next) => {
            onSettings(next);
            setValue(next);
          }}
        />
      );
    }
    render(<Parent />);
    return onSettings;
  }

  it("5: at least one reminder — 0 is put right to 1 when she leaves the field", () => {
    const onSettings = box();
    const count = screen.getByLabelText("Number of reminders") as HTMLInputElement;
    expect(count.min).toBe("1");
    fireEvent.change(count, { target: { value: "0" } });
    expect(onSettings).not.toHaveBeenCalled();
    fireEvent.blur(count);
    expect(onSettings).toHaveBeenLastCalledWith({ ...settings, max_auto: 1 });
    expect(count.value).toBe("1");
  });

  it("6: a field can be cleared and retyped: 3 → empty → 7 gives 7, not 37 or 30", () => {
    const onSettings = box();
    const days = screen.getByLabelText("Days between reminders") as HTMLInputElement;
    fireEvent.change(days, { target: { value: "" } });
    expect(days.value).toBe("");
    expect(onSettings).not.toHaveBeenCalled();
    fireEvent.change(days, { target: { value: "7" } });
    expect(days.value).toBe("7");
    expect(onSettings).toHaveBeenLastCalledWith({ ...settings, interval_days: 7 });
  });

  it("6: out of range while typing is held, and put right on leaving", () => {
    const onSettings = box();
    const days = screen.getByLabelText("Days between reminders") as HTMLInputElement;
    fireEvent.change(days, { target: { value: "37" } });
    expect(days.value).toBe("37");
    expect(onSettings).not.toHaveBeenCalled();
    fireEvent.blur(days);
    expect(onSettings).toHaveBeenLastCalledWith({ ...settings, interval_days: 30 });
  });

  it("6: left empty, it goes back to what it was", () => {
    const onSettings = box();
    const days = screen.getByLabelText("Days between reminders") as HTMLInputElement;
    fireEvent.change(days, { target: { value: "" } });
    fireEvent.blur(days);
    expect(days.value).toBe("3");
    expect(onSettings).not.toHaveBeenCalled();
  });

  it("7: a stopped follow-up on a FAILED email says so and offers no Start", () => {
    const failed = { ...message(followUp({ status: "stopped" })), status: "failed" };
    render(<FollowUpBar fileId="LF-1" message={failed as MessageDetail} />);
    expect(screen.getByText("Stopped — the email failed")).toBeTruthy();
    expect(buttonNames()).toEqual([]);
  });

  it("7: the same in the list, from the row's email_status", () => {
    mockFollowUps.mockReturnValue({
      data: [
        row("f", { status: "stopped" }, { email_status: "failed" }),
        row("s", { status: "stopped" }),
      ],
    });
    render(<FollowUpsList fileId="LF-1" selectedId={null} onOpen={vi.fn()} />);
    const [failedRow, stoppedRow] = screen.getAllByRole("row").slice(1) as HTMLElement[];
    expect(within(failedRow as HTMLElement).getByText("Stopped — the email failed")).toBeTruthy();
    expect(
      within(failedRow as HTMLElement).queryByRole("button", { name: "Start follow-ups" }),
    ).toBeNull();
    expect(
      within(stoppedRow as HTMLElement).getByRole("button", { name: "Start follow-ups" }),
    ).toBeTruthy();
  });
});

// --------------------------------------------------------------------------------------------- //
describe("LP-1014 fix (11-08) — spent reminders with nothing missing", () => {
  it.each([
    [[], "finished"],
    [["W-2"], "no_reply"],
    [["a reply"], "no_reply"],
  ])("on, 2 of 2 sent, waiting for %o → %s", (waiting, state) => {
    expect(followUpState(followUp({ auto_sent: 2, waiting_for: waiting }))).toBe(state);
  });

  it("reads Everything arrived, with a neutral pill and no buttons", () => {
    const done = followUp({ auto_sent: 2, waiting_for: [] });
    expect(followUpPill(done)).toEqual({ label: "Finished", tone: "neutral" });
    render(<FollowUpBar fileId="LF-1" message={message(done)} />);
    expect(screen.getByText("Everything arrived")).toBeTruthy();
    expect(buttonNames()).toEqual([]);
  });

  it("is not put first in the list, and not in red", () => {
    mockFollowUps.mockReturnValue({
      data: [
        row("newest"),
        row("arrived", { auto_sent: 2, waiting_for: [] }),
        row("no-reply", { auto_sent: 2 }),
      ],
    });
    render(<FollowUpsList fileId="LF-1" selectedId={null} onOpen={vi.fn()} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("button")[0]?.textContent)).toEqual([
      "Subject no-reply",
      "Subject newest",
      "Subject arrived",
    ]);
    expect(rows[2]?.className).not.toContain("text-danger");
  });
});

describe("LP-1014 fix 2 (11-08) — paused with nothing missing", () => {
  it.each([
    [[], "finished"],
    [["W-2"], "paused"],
    [["a reply"], "paused"],
  ])("paused, waiting for %o → %s", (waiting, state) => {
    expect(followUpState(followUp({ status: "paused", waiting_for: waiting }))).toBe(state);
  });

  it("reads Everything arrived with no Resume", () => {
    render(
      <FollowUpBar
        fileId="LF-1"
        message={message(followUp({ status: "paused", waiting_for: [] }))}
      />,
    );
    expect(screen.getByText("Everything arrived")).toBeTruthy();
    expect(buttonNames()).toEqual([]);
  });
});

// --------------------------------------------------------------------------------------------- //
describe("LP-1015", () => {
  it("No reply: Stop clears it", () => {
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ auto_sent: 2 }))} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(mockMutate.mock.calls[0]?.[0]).toEqual({ kind: "stop" });
  });

  it("No reply in the list: Send now and Stop", () => {
    mockFollowUps.mockReturnValue({ data: [row("n", { auto_sent: 2 })] });
    render(<FollowUpsList fileId="LF-1" selectedId={null} onOpen={vi.fn()} />);
    const [only] = screen.getAllByRole("row").slice(1) as HTMLElement[];
    const names = within(only as HTMLElement)
      .getAllByRole("button")
      .slice(1) // the subject
      .map((b) => b.textContent);
    expect(names).toEqual(["Send now", "Stop"]);
  });

  it("a blocked address: the bar says so, no buttons", () => {
    mockFollowUps.mockReturnValue({
      data: [row("m1", { status: "stopped" }, { recipient_suppressed: true })],
    });
    render(<FollowUpBar fileId="LF-1" message={message(followUp({ status: "stopped" }))} />);
    expect(screen.getByText("Stopped — address blocked (bounce or complaint)")).toBeTruthy();
    expect(buttonNames()).toEqual([]);
  });

  it("a blocked address in the list: says so, no Start; an unblocked stopped row keeps Start", () => {
    mockFollowUps.mockReturnValue({
      data: [
        row("b", { status: "stopped" }, { recipient_suppressed: true }),
        row("s", { status: "stopped" }),
      ],
    });
    render(<FollowUpsList fileId="LF-1" selectedId={null} onOpen={vi.fn()} />);
    const [blockedRow, stoppedRow] = screen.getAllByRole("row").slice(1) as HTMLElement[];
    expect(
      within(blockedRow as HTMLElement).getByText(
        "Stopped — address blocked (bounce or complaint)",
      ),
    ).toBeTruthy();
    expect(
      within(blockedRow as HTMLElement).queryByRole("button", { name: "Start follow-ups" }),
    ).toBeNull();
    expect(
      within(stoppedRow as HTMLElement).getByRole("button", { name: "Start follow-ups" }),
    ).toBeTruthy();
  });

  it("a bounce both fails the email and blocks the address: it says the email failed", () => {
    const stopped = followUp({ status: "stopped" });
    expect(followUpState(stopped, true, true, true)).toBe("stopped_failed");
    expect(followUpState(stopped, true, false, true)).toBe("stopped_blocked");
  });
});
