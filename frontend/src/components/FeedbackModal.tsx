import {
  Accordion,
  Alert,
  Anchor,
  Box,
  Button,
  Checkbox,
  Code,
  CopyButton,
  Divider,
  Group,
  Modal,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_TYPE_ID,
  FEEDBACK_EMAIL,
  FEEDBACK_TYPES,
  type FeedbackResult,
  collectDiagnostics,
  getType,
  submitFeedback,
} from "@/config/feedback";

type FeedbackModalProps = {
  opened: boolean;
  onClose: () => void;
  /** Current page title, so a note says which screen it came from. */
  view: string;
};

export function FeedbackModal({ opened, onClose, view }: FeedbackModalProps) {
  // The accordion can collapse to nothing; `typeId` holds the last real
  // selection so a collapsed panel never submits a category of `null`.
  const [typeId, setTypeId] = useState<string>(DEFAULT_TYPE_ID);
  const [openItem, setOpenItem] = useState<string | null>(DEFAULT_TYPE_ID);
  // One shared box, never one per category: switching category must never eat
  // what somebody has already typed.
  const [message, setMessage] = useState("");
  const [replyTo, setReplyTo] = useState("");
  const [includeContext, setIncludeContext] = useState(true);
  const [showContext, setShowContext] = useState(false);
  const [result, setResult] = useState<FeedbackResult | null>(null);
  const [busy, setBusy] = useState(false);
  const statusRef = useRef<HTMLDivElement>(null);

  const active = getType(typeId);
  const diagnostics = useMemo(
    () => (opened ? collectDiagnostics({ view }) : {}),
    [opened, view],
  );

  // In a tall modal with a pinned footer the status line often renders below
  // the fold, which looks identical to a button that did nothing.
  useEffect(() => {
    if (result) statusRef.current?.scrollIntoView({ block: "nearest" });
  }, [result]);

  const handleSubmit = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const outcome = await submitFeedback({
        typeId,
        message,
        replyTo,
        diagnostics: includeContext ? diagnostics : null,
      });
      setResult(outcome);
      if (outcome.mailto) {
        // `mailto:` hands off to the mail client without unloading the page,
        // so the copy-out panel below stays available either way.
        window.location.href = outcome.mailto;
      }
    } finally {
      setBusy(false);
    }
  };

  const handleClose = () => {
    onClose();
    // Keep the draft if nothing was delivered; clear it once it has gone.
    if (result && result.status !== "error") {
      setMessage("");
      setReplyTo("");
      setResult(null);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={<Text fw={700}>Send feedback</Text>}
      size="lg"
      radius="md"
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Pick what this is about — opening an item shows what a useful note of
          that kind contains.
        </Text>

        <Accordion
          value={openItem}
          onChange={(next) => {
            setOpenItem(next);
            if (next) setTypeId(next);
          }}
          variant="separated"
          radius="md"
        >
          {FEEDBACK_TYPES.map((entry) => (
            <Accordion.Item key={entry.id} value={entry.id}>
              <Accordion.Control
                icon={<span aria-hidden="true">{entry.icon}</span>}
              >
                <Text size="sm" fw={typeId === entry.id ? 700 : 500}>
                  {entry.label}
                </Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Text size="xs" c="dimmed">
                  {entry.blurb}
                </Text>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>

        <Textarea
          label={`Your note — ${active.label.toLowerCase()}`}
          placeholder={active.placeholder}
          value={message}
          onChange={(event) => setMessage(event.currentTarget.value)}
          autosize
          minRows={6}
          maxRows={14}
          spellCheck
        />

        <TextInput
          label="Your email address (optional)"
          description="Leave blank to stay anonymous — an anonymous note is still a good note. Fill it in only if you want a reply."
          placeholder="you@example.com"
          type="email"
          value={replyTo}
          onChange={(event) => setReplyTo(event.currentTarget.value)}
        />

        <Box>
          <Checkbox
            checked={includeContext}
            onChange={(event) => setIncludeContext(event.currentTarget.checked)}
            label="Attach which screen I was on and what I am running"
            description="Nothing beyond what is listed below — no filenames, no accounts, nothing stored in your browser."
          />
          <Anchor
            component="button"
            type="button"
            size="xs"
            mt={6}
            ml={30}
            onClick={() => setShowContext((shown) => !shown)}
          >
            {showContext ? "Hide what gets attached" : "Show exactly what gets attached"}
          </Anchor>
          {showContext && (
            <Code block mt={8} style={{ fontSize: "0.72rem" }}>
              {Object.entries(diagnostics)
                .map(([key, value]) => `${key.padEnd(9)}  ${value}`)
                .join("\n")}
            </Code>
          )}
        </Box>

        <div ref={statusRef}>
          {result && (
            <Alert
              color={
                result.status === "sent"
                  ? "teal"
                  : result.status === "compose"
                    ? "blue"
                    : "orange"
              }
              radius="md"
              title={
                result.status === "sent"
                  ? "Delivered"
                  : result.status === "compose"
                    ? "Handed to your mail app"
                    : "Not sent yet"
              }
            >
              <Text size="sm">{result.message}</Text>
            </Alert>
          )}
        </div>

        {/* Rule zero: a note must never be able to vanish. If the mail client
            is missing or the relay is unreachable, the composed text is right
            here to copy, with the address to paste it to. */}
        {result && result.status !== "error" && (
          <Box>
            <Divider
              mb="xs"
              label={<Text size="xs">If nothing happened, copy it out by hand</Text>}
              labelPosition="left"
            />
            <Text size="xs" c="dimmed" mb={6}>
              Send it to{" "}
              <Anchor href={`mailto:${FEEDBACK_EMAIL}`} size="xs">
                {FEEDBACK_EMAIL}
              </Anchor>{" "}
              with the subject <Code>{result.subject}</Code>.
            </Text>
            <Code block style={{ fontSize: "0.72rem", maxHeight: 200, overflow: "auto" }}>
              {result.transcript}
            </Code>
            <Group mt="xs" gap="xs">
              <CopyButton value={result.transcript}>
                {({ copied, copy }) => (
                  <Button
                    size="xs"
                    variant={copied ? "filled" : "light"}
                    color={copied ? "teal" : "navy"}
                    onClick={copy}
                  >
                    {copied ? "Copied to clipboard" : "Copy the message"}
                  </Button>
                )}
              </CopyButton>
              {result.mailto && (
                <Button
                  size="xs"
                  variant="subtle"
                  component="a"
                  href={result.mailto}
                >
                  Open my mail app again
                </Button>
              )}
            </Group>
          </Box>
        )}

        <Group justify="flex-end" gap="sm">
          <Button variant="subtle" color="gray" onClick={handleClose}>
            Close
          </Button>
          <Button onClick={handleSubmit} loading={busy}>
            {result && result.status !== "error" ? "Send again" : "Send feedback"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
