/**
 * Opening the processor's own compose window (LP-855).
 *
 * EVERY ROUTE TAKES THE BODY AS PLAIN TEXT. `mailto:` is plain by RFC 6068 and the three web
 * routes are no better — there is no compose URL anywhere that carries formatting. So the button
 * does two things: it puts the RICH body on the clipboard and opens the window with To and Subject
 * filled and **the body left empty**, then says "Paste into the message — ⌘V".
 *
 * FILLING THE BODY WITH STRIPPED PLAIN TEXT WOULD BE WORSE THAN LEAVING IT EMPTY. It hands the
 * processor a message that LOOKS finished and has quietly lost its structure — bullets run
 * together, bold gone, the nested document guidance flattened — and nothing on screen prompts them
 * to notice. An empty body is obviously unfinished, which is the whole point.
 *
 * AND IT RETIRES THE LENGTH PROBLEM. `mailto_max_chars` exists because a long body overflows the
 * URL, and there is no longer a body in the URL. The ceiling stays as a guard on subject plus
 * address, which are bounded by the schema anyway; what stops is hiding the button because a
 * message is long.
 */
import type { MailClient } from "@/lib/api/preferences";

/**
 * Build the compose URL for one client.
 *
 * ENCODED WITH `URLSearchParams` FOR THE WEB ROUTES and `encodeURIComponent` for `mailto:`, because
 * they are different grammars. `URLSearchParams` encodes a space as `+`, which is correct in a
 * query string and WRONG in a `mailto:` header — RFC 6068 wants `%20`, and a subject reading
 * "Documents+we+need" is what the difference looks like in a borrower's inbox.
 */
export function composeUrl(
  client: MailClient,
  { to, subject }: { to: string; subject: string },
): string {
  switch (client) {
    case "gmail": {
      const params = new URLSearchParams({ view: "cm", fs: "1", to, su: subject, body: "" });
      return `https://mail.google.com/mail/?${params.toString()}`;
    }
    case "outlook_work": {
      const params = new URLSearchParams({ to, subject, body: "" });
      return `https://outlook.office.com/mail/deeplink/compose?${params.toString()}`;
    }
    case "outlook_personal": {
      const params = new URLSearchParams({ to, subject, body: "" });
      return `https://outlook.live.com/mail/0/deeplink/compose?${params.toString()}`;
    }
    default: {
      // RFC 6068: the address is in the path and the headers are a query string, both
      // percent-encoded.
      //
      // LP-855 REVIEW — `encodeURIComponent` DOES NOT LEAVE `@` ALONE. This comment said it did;
      // it encodes it to `%40`, so the URL built here was `mailto:p%40x.com?...`. Most clients
      // decode that and some do not, and the ones that do not open a compose window with an empty
      // To — which looks like the button half-worked rather than like an encoding problem. The
      // literal `@` is what every client handles and what every example in the RFC shows, so it is
      // put back after encoding rather than the claim being left standing.
      const headers = `subject=${rfc6068(subject)}&body=`;
      return `mailto:${encodeURIComponent(to).replace(/%40/g, "@")}?${headers}`;
    }
  }
}

/**
 * Percent-encoding for a `mailto:` header value.
 *
 * `encodeURIComponent` ALREADY DOES THE RIGHT THING except for a handful of characters it leaves
 * alone that RFC 6068 reserves in this position. `&` would end the header and start another, which
 * is how a subject containing "Smith & Sons" truncates and invents a header called ` Sons`.
 */
function rfc6068(value: string): string {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

/** What the primary button says, before it does anything. */
export function composeButtonLabel(client: MailClient | null): string {
  // UNTIL THEY ANSWER, IT SAYS "mail app" — the honest label for `mailto:`, and the one that does
  // not claim we know something we have not asked.
  if (client === null) return "Copy & open mail app";
  return client === "mailto" ? "Copy & open mail app" : `Copy & open ${labelFor(client)}`;
}

function labelFor(client: MailClient): string {
  switch (client) {
    case "gmail":
      return "Gmail";
    case "outlook_work":
    case "outlook_personal":
      return "Outlook";
    default:
      return "mail app";
  }
}

/** The client to actually use. `null` — nobody asked — behaves as the safe answer. */
export function effectiveClient(client: MailClient | null): MailClient {
  return client ?? "mailto";
}
