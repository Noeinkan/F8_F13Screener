import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Loader, Stack, Text, TextInput, Title } from "@mantine/core";
import { useDemoSession } from "@/demo/useDemoSession";

/**
 * The email gate in front of the public demo.
 *
 * On a normal deployment this renders nothing of its own: the session probe
 * answers "not a demo" and the dashboard mounts exactly as before.
 *
 * Two steps, and the component is a small state machine over them. A visitor
 * gives an address and is told to go and read it; the link in that mail comes
 * back to this same page carrying `?t=`, which is redeemed for a session
 * cookie before anything else renders. The token is stripped from the address
 * bar on the way through, so a screenshot or a pasted URL does not carry a
 * working key any further than the inbox it was sent to.
 */
type Phase = "form" | "sent" | "redeeming";

export function DemoGate({ children }: { children: React.ReactNode }) {
  const session = useDemoSession();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [phase, setPhase] = useState<Phase>("form");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const redeemTried = useRef(false);

  const needsAccess = session.data?.demo === true && session.data.authenticated === false;
  const linkTtl = session.data?.limits?.linkTtlMinutes ?? 30;

  const post = async (path: string, body: unknown) => {
    const response = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => null);
    return { ok: response.ok, payload };
  };

  const requestLink = async () => {
    const candidate = email.trim();
    if (!candidate) return;
    setSubmitting(true);
    setError(null);
    try {
      const { ok, payload } = await post("/api/demo/request-access", { email: candidate });
      if (ok) {
        setPhase("sent");
        setNotice(payload?.message ?? "Link sent. Check your inbox.");
        return;
      }
      setError(payload?.detail?.message ?? "That did not work. Try again in a moment.");
    } catch {
      setError("Could not reach the demo. It may be restarting — try again shortly.");
    } finally {
      setSubmitting(false);
    }
  };

  // Redeem the token the emailed link carries, before the gate paints a form
  // the visitor has already dealt with.
  useEffect(() => {
    if (!needsAccess || redeemTried.current) return;
    const url = new URL(window.location.href);
    const token = url.searchParams.get("t");
    if (!token) return;
    redeemTried.current = true;
    setPhase("redeeming");
    url.searchParams.delete("t");
    window.history.replaceState({}, "", url.toString());
    void (async () => {
      const { ok, payload } = await post("/api/demo/redeem", { token });
      if (ok) {
        await queryClient.invalidateQueries({ queryKey: ["demo-session"] });
        return;
      }
      setPhase("form");
      setError(payload?.detail?.message ?? "That link is no longer good. Ask for a new one.");
    })();
  }, [needsAccess, queryClient]);

  if (session.isLoading) {
    return (
      <Stack align="center" justify="center" style={{ minHeight: "100vh" }}>
        <Loader color="var(--f8-accent)" />
      </Stack>
    );
  }

  if (!needsAccess) return <>{children}</>;

  return (
    <Stack
      align="center"
      justify="center"
      style={{ minHeight: "100vh", background: "var(--f8-bg)", padding: "1.5rem" }}
    >
      <Stack
        gap="md"
        style={{
          width: "100%",
          maxWidth: 440,
          background: "var(--f8-surface)",
          border: "1px solid var(--f8-border)",
          borderRadius: "0.75rem",
          padding: "1.75rem",
        }}
      >
        <div>
          <Title order={3} style={{ color: "var(--f8-ink)" }}>
            13F Screener — demo
          </Title>
          <Text size="sm" c="dimmed" mt={6}>
            A read-only copy of the dashboard over a frozen snapshot of SEC 13F
            filings. Leave an address and I will send you a link that opens it.
          </Text>
        </div>

        {phase === "redeeming" ? (
          <Stack align="center" gap="xs" py="md">
            <Loader color="var(--f8-accent)" size="sm" />
            <Text size="sm" c="dimmed">
              Opening the demo…
            </Text>
          </Stack>
        ) : phase === "sent" ? (
          <Stack gap="sm">
            <Alert color="green" variant="light" title="Check your inbox">
              {notice}
            </Alert>
            <Button
              variant="subtle"
              color="gray"
              onClick={() => {
                setPhase("form");
                setNotice(null);
              }}
            >
              Use a different address
            </Button>
          </Stack>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void requestLink();
            }}
          >
            <Stack gap="sm">
              <TextInput
                type="email"
                label="Your email"
                placeholder="you@company.com"
                value={email}
                onChange={(event) => setEmail(event.currentTarget.value)}
                autoFocus
                data-autofocus
                required
              />
              <Button type="submit" loading={submitting} color="var(--f8-accent)">
                Email me the link
              </Button>
              <Text size="xs" c="dimmed">
                The link works for {linkTtl} minutes. No account is created, and the
                address is used to send that one link — nothing else.
              </Text>
            </Stack>
          </form>
        )}

        {error ? (
          <Alert color="red" variant="light" title="Not open">
            {error}
          </Alert>
        ) : null}

        <Text size="xs" c="dimmed">
          More of these at{" "}
          <a
            href="https://noeinsolutions.com/builds.html"
            style={{ color: "var(--f8-accent)", fontWeight: 600 }}
          >
            noeinsolutions.com/builds
          </a>
        </Text>
      </Stack>
    </Stack>
  );
}
