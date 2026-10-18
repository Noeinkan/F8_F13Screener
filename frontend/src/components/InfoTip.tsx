import { ReactNode } from "react";
import { ActionIcon, Popover, Text } from "@mantine/core";

/**
 * A small ⓘ that opens a note on click. For method explanations a
 * daily user reads once: they stay one click away instead of taking a
 * paragraph on every visit. A popover, not a tooltip, so it also opens on a
 * phone tap.
 */
export function InfoTip({ children, label = "About this section" }: { children: ReactNode; label?: string }) {
  return (
    <Popover width={320} position="bottom-start" shadow="md" withArrow>
      <Popover.Target>
        <ActionIcon variant="subtle" color="gray" size="sm" radius="xl" aria-label={label}>
          <span aria-hidden="true" style={{ fontSize: "0.85rem", lineHeight: 1 }}>
            ⓘ
          </span>
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown>
        <Text size="sm" c="dimmed">
          {children}
        </Text>
      </Popover.Dropdown>
    </Popover>
  );
}
