import { ReactNode } from "react";
import { Group } from "@mantine/core";
import { InfoTip } from "@/components/InfoTip";

type SectionHeaderProps = {
  title: string;
  /** Method notes: shown behind an ⓘ next to the title, not as a paragraph. */
  caption?: ReactNode;
  right?: ReactNode;
};

export function SectionHeader({ title, caption, right }: SectionHeaderProps) {
  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Group gap={6} wrap="nowrap" align="center">
          <h2 className="f8-section-title">{title}</h2>
          {caption ? <InfoTip>{caption}</InfoTip> : null}
        </Group>
        {right ? <div style={{ flexShrink: 0 }}>{right}</div> : null}
      </Group>
    </div>
  );
}
