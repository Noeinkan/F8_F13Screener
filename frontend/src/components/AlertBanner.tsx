import { ReactNode } from "react";
import { Alert } from "@mantine/core";

export type AlertVariant = "info" | "warning" | "success" | "error";

type AlertBannerProps = {
  variant?: AlertVariant;
  title?: ReactNode;
  children: ReactNode;
  icon?: ReactNode;
  withCloseButton?: boolean;
  onClose?: () => void;
};

const VARIANT_COLOR: Record<AlertVariant, string> = {
  info: "navy",
  warning: "yellow",
  success: "teal",
  error: "red",
};

export function AlertBanner({
  variant = "info",
  title,
  children,
  icon,
  withCloseButton = false,
  onClose,
}: AlertBannerProps) {
  return (
    <Alert
      variant="light"
      color={VARIANT_COLOR[variant]}
      title={title}
      icon={icon}
      withCloseButton={withCloseButton}
      onClose={onClose}
      mb="md"
      radius="md"
    >
      {children}
    </Alert>
  );
}