import { useState } from "react";
import { FeedbackModal } from "@/components/FeedbackModal";
import { KOFI_URL } from "@/config/externalLinks";

type TopBarProps = {
  pageTitle: string;
};

export function TopBar({ pageTitle }: TopBarProps) {
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  // Layout and pill styling live in styles.css, not inline, so the media
  // queries that keep both actions on screen at phone width can reach them.
  return (
    <div className="f8-topbar">
      <strong className="f8-topbar-brand">F8 13F Screener</strong>
      <span className="f8-topbar-page">{pageTitle}</span>
      <button
        type="button"
        onClick={() => setFeedbackOpen(true)}
        className="f8-topbar-pill feedback-button"
        title="Tell me what is broken, confusing or missing"
        aria-label="Send feedback about this dashboard"
      >
        <span aria-hidden="true">💬</span>
        Feedback
      </button>
      {/* Wording must stay "Support" (not "Donate"): Ko-fi reserves donation
          wording for registered non-profits and enforces it after the fact. */}
      <a
        href={KOFI_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="f8-topbar-pill donate-button"
        title="Support this project on Ko-fi"
        aria-label="Support this project on Ko-fi"
      >
        <span aria-hidden="true">☕</span>
        Support
      </a>
      <FeedbackModal
        opened={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        view={pageTitle}
      />
    </div>
  );
}
