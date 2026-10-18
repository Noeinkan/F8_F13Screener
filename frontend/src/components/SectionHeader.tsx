import { ReactNode } from "react";
import { Group } from "@mantine/core";

type SectionHeaderProps = {
  title: string;
  caption?: ReactNode;
  right?: ReactNode;
};

export function SectionHeader({ title, caption, right }: SectionHeaderProps) {
  return (
    <div style={{ marginBottom: "0.5rem" }}>
      {/* wrap: on a phone the export links drop below the title instead of
          pushing the page wider than the screen. */}
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="md">
        <div>
          <h2 className="f8-section-title">{title}</h2>
          {caption ? <p className="f8-section-caption">{caption}</p> : null}
        </div>
        {right ? <div style={{ flexShrink: 0 }}>{right}</div> : null}
      </Group>
    </div>
  );
}