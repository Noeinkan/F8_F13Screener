// Feedback delivery — relay first, mail client second, copy-out always.
//
// No backend involvement on purpose: this app is also run locally from a clone,
// where the server *is* the visitor's machine, so SMTP credentials or API keys
// could never ship. The relay is called straight from the browser with a public
// form key (that is what those keys are for) and `mailto:` is the fallback that
// works on a fresh clone with no account at all.
//
// Configure with, at most, three optional Vite env vars:
//
//   VITE_FEEDBACK_EMAIL       destination inbox (defaults to the studio address)
//   VITE_FEEDBACK_ENDPOINT    JSON relay (Web3Forms, Formspree, your own)
//   VITE_FEEDBACK_ACCESS_KEY  public form key; Web3Forms wants it in the body
//
// Every result carries a `transcript`. The modal renders it so that a failed
// hand-off can still be copied out by hand — a note must never be able to
// vanish silently.

const FEEDBACK_EMAIL_FALLBACK = "andrea.aita@noeinsolutions.com";

export const APP_NAME = "F8 13F Screener";

export const FEEDBACK_EMAIL: string =
  (import.meta.env.VITE_FEEDBACK_EMAIL as string | undefined)?.trim() ||
  FEEDBACK_EMAIL_FALLBACK;

const FEEDBACK_ENDPOINT: string =
  (import.meta.env.VITE_FEEDBACK_ENDPOINT as string | undefined)?.trim() || "";

const FEEDBACK_ACCESS_KEY: string =
  (import.meta.env.VITE_FEEDBACK_ACCESS_KEY as string | undefined)?.trim() || "";

export const MIN_MESSAGE_CHARS = 12;
export const MAX_MESSAGE_CHARS = 4000;

export type FeedbackType = {
  id: string;
  icon: string;
  label: string;
  subject: string;
  blurb: string;
  placeholder: string;
};

// `placeholder` is a template, not a hint — people fill in a shape far more
// readily than they compose from nothing. Order is triage order.
export const FEEDBACK_TYPES: FeedbackType[] = [
  {
    id: "bug",
    icon: "🐞",
    label: "Something is broken",
    subject: "Bug report",
    blurb:
      "A page that will not load, a chart that stays empty, a control that " +
      "does nothing, an error on screen. The three lines below are all I need.",
    placeholder: "What I did:\nWhat I expected:\nWhat happened instead:",
  },
  {
    id: "data",
    icon: "📉",
    label: "The numbers look wrong",
    subject: "Data quality",
    blurb:
      "A position, value or quarter that does not match the filing you were " +
      "reading. Name the fund and the quarter if you can — that is what lets " +
      "me trace it back to the source filing on EDGAR.",
    placeholder:
      "Fund:\nQuarter:\nWhat the dashboard shows:\nWhat the filing says:",
  },
  {
    id: "idea",
    icon: "💡",
    label: "I have an idea",
    subject: "Feature idea",
    blurb: "Anything you wish this did.",
    placeholder:
      "What would you like to be able to do, and what decision would it help " +
      "you make?",
  },
  {
    id: "usability",
    icon: "🧭",
    label: "Something confused me",
    subject: "Usability",
    blurb:
      "A label that reads wrong, a number you could not interpret, a control " +
      "you could not find. Confusion is a bug I cannot see from here.",
    placeholder: "What were you trying to do, and where did it lose you?",
  },
  {
    id: "impression",
    icon: "💬",
    label: "General impressions",
    subject: "General feedback",
    blurb: "What works, what does not. Blunt is useful — polite is not.",
    placeholder: "Anything you want to say about the project.",
  },
];

export const DEFAULT_TYPE_ID = FEEDBACK_TYPES[0].id;

const BY_ID = new Map(FEEDBACK_TYPES.map((entry) => [entry.id, entry]));

/** Never throws on an unknown id — it can only come from a stale client. */
export function getType(typeId: string | null | undefined): FeedbackType {
  return BY_ID.get(typeId ?? "") ?? FEEDBACK_TYPES[0];
}

export type Diagnostics = Record<string, string>;

type DiagnosticsInput = {
  view: string;
};

/**
 * Boring facts only, assembled from an explicit argument plus browser globals.
 *
 * The modal promises "nothing beyond what you see here", so this function is
 * deliberately the only place a context value can be introduced: it reads no
 * storage, no cookies, no query string and no app state, which is what keeps
 * that promise true through later edits.
 */
export function collectDiagnostics({ view }: DiagnosticsInput): Diagnostics {
  return {
    View: view || "—",
    Version: (import.meta.env.VITE_APP_VERSION as string | undefined) || "dev",
    Browser: browserName(),
    Platform: navigator.platform || "—",
    Language: navigator.language || "—",
    Viewport: `${window.innerWidth}×${window.innerHeight}`,
  };
}

function browserName(): string {
  const ua = navigator.userAgent;
  const match =
    /(Firefox|Edg|OPR|Chrome|Safari)\/([\d.]+)/.exec(ua) ?? null;
  if (!match) return "unknown";
  const names: Record<string, string> = { Edg: "Edge", OPR: "Opera" };
  return `${names[match[1]] ?? match[1]} ${match[2].split(".")[0]}`;
}

/** Returns a human-readable problem, or null. Always gives a reason. */
export function validateFeedback(
  message: string | null | undefined,
  replyTo: string | null | undefined,
): string | null {
  const text = (message ?? "").trim();
  if (!text) return "Write a line or two first — the box is empty.";
  if (text.length < MIN_MESSAGE_CHARS) {
    return "A few more words, please — I want to be able to act on this.";
  }
  if (text.length > MAX_MESSAGE_CHARS) {
    return `That is ${text.length.toLocaleString()} characters; the limit is ${MAX_MESSAGE_CHARS.toLocaleString()}.`;
  }
  const address = (replyTo ?? "").trim();
  if (
    address &&
    (!address.includes("@") || address.startsWith("@") || address.endsWith("@"))
  ) {
    return "That reply address does not look like an email. Leave it blank to stay anonymous.";
  }
  return null;
}

/** ASCII only — emoji survives URL encoding but not every mail client. */
export function buildSubject(typeId: string | null | undefined): string {
  return `[${APP_NAME}] ${getType(typeId).subject}`;
}

type BodyInput = {
  typeId: string | null | undefined;
  message: string;
  replyTo?: string | null;
  diagnostics?: Diagnostics | null;
};

/** Fixed sections in fixed order, so a full inbox stays skimmable. */
export function buildBody({
  typeId,
  message,
  replyTo,
  diagnostics,
}: BodyInput): string {
  const lines = [
    `Type:  ${getType(typeId).label}`,
    `Sent:  ${sentStamp()}`,
    `Reply: ${(replyTo ?? "").trim() || "not given (anonymous)"}`,
    "",
    "--- Message ---",
    (message ?? "").trim(),
  ];
  const keys = diagnostics ? Object.keys(diagnostics) : [];
  if (keys.length) {
    const width = Math.max(...keys.map((key) => key.length));
    lines.push("", "--- Context ---");
    for (const key of keys) {
      lines.push(`${key.padEnd(width)}  ${diagnostics![key]}`);
    }
  }
  lines.push("", `--- Sent from the ${APP_NAME} feedback button ---`);
  return lines.join("\n");
}

function sentStamp(): string {
  const now = new Date();
  const date = now.toISOString().slice(0, 10);
  const time = now.toTimeString().slice(0, 5);
  const zone =
    new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
      .formatToParts(now)
      .find((part) => part.type === "timeZoneName")?.value ?? "";
  return `${date} ${time} ${zone}`.trim();
}

/**
 * `encodeURIComponent` is the whole trick: it is what stops an `&`, a newline
 * or a quote in the message from truncating the body at the first ampersand.
 */
export function buildMailto(subject: string, body: string): string {
  return (
    `mailto:${FEEDBACK_EMAIL}` +
    `?subject=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`
  );
}

export type FeedbackStatus = "sent" | "compose" | "error";

export type FeedbackResult = {
  status: FeedbackStatus;
  message: string;
  mailto?: string;
  transcript: string;
  subject: string;
};

/**
 * Superset payload — Web3Forms and Formspree each ignore what they do not
 * know, so one object covers both with no per-provider branch.
 */
function relayPayload(
  subject: string,
  body: string,
  typeId: string,
  replyTo: string,
): Record<string, string> {
  const payload: Record<string, string> = {
    subject,
    _subject: subject, // Formspree's spelling
    from_name: APP_NAME,
    // Used as Reply-To, and rejected if malformed — so an anonymous note falls
    // back to the maintainer's own address rather than being dropped.
    email: replyTo.trim() || FEEDBACK_EMAIL,
    feedback_type: typeId,
    message: body,
  };
  if (FEEDBACK_ACCESS_KEY) payload.access_key = FEEDBACK_ACCESS_KEY;
  return payload;
}

/**
 * Never rejects. A stack trace shown to somebody reporting a bug is a poor
 * first impression, so a transport failure comes back as a reason to show.
 */
async function postToRelay(
  payload: Record<string, string>,
): Promise<{ ok: boolean; detail: string }> {
  try {
    const response = await fetch(FEEDBACK_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10_000),
    });
    if (response.ok) return { ok: true, detail: "" };
    return { ok: false, detail: `HTTP ${response.status}` };
  } catch (err) {
    // `fetch` throws TypeError for every network-level failure — offline, DNS,
    // CORS, blocked by an extension — so the raw name tells a visitor nothing.
    const name = err instanceof Error ? err.name : "";
    if (name === "TimeoutError" || name === "AbortError") {
      return { ok: false, detail: "it timed out" };
    }
    if (name === "TypeError") {
      return { ok: false, detail: "could not be reached" };
    }
    return { ok: false, detail: name || "unknown error" };
  }
}

type SubmitInput = {
  typeId: string | null | undefined;
  message: string;
  replyTo?: string | null;
  diagnostics?: Diagnostics | null;
};

/** Validate, format, deliver. The only networked call in this module. */
export async function submitFeedback({
  typeId,
  message,
  replyTo,
  diagnostics,
}: SubmitInput): Promise<FeedbackResult> {
  const problem = validateFeedback(message, replyTo);
  if (problem) {
    return { status: "error", message: problem, transcript: "", subject: "" };
  }

  const subject = buildSubject(typeId);
  const body = buildBody({ typeId, message, replyTo, diagnostics });

  if (FEEDBACK_ENDPOINT) {
    const { ok, detail } = await postToRelay(
      relayPayload(subject, body, getType(typeId).id, replyTo ?? ""),
    );
    if (ok) {
      // The only path that has earned the word "sent".
      return {
        status: "sent",
        message: "Sent — thank you. That genuinely helps.",
        transcript: body,
        subject,
      };
    }
    return {
      status: "compose",
      message:
        `The send relay ${detail}, so I opened your mail app with the message ` +
        "ready instead. Nothing has been lost.",
      mailto: buildMailto(subject, body),
      transcript: body,
      subject,
    };
  }

  return {
    status: "compose",
    message:
      "Your mail app should be opening with the message ready — press send " +
      "there and it reaches me.",
    mailto: buildMailto(subject, body),
    transcript: body,
    subject,
  };
}
