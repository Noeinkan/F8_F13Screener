import { Anchor } from "@mantine/core";

type ExportLinkProps = {
  href: string;
  label: string;
  fileName?: string;
  target?: "_blank" | "_self";
};

export function ExportLink({ href, label, fileName, target = "_blank" }: ExportLinkProps) {
  return (
    <Anchor
      href={href}
      target={target}
      rel={target === "_blank" ? "noopener noreferrer" : undefined}
      download={fileName}
      style={{ fontSize: "0.85rem", fontWeight: 600 }}
    >
      {label}
    </Anchor>
  );
}

type DownloadButtonProps = {
  href: string;
  label: string;
  fileName?: string;
};

export function DownloadButton({ href, label, fileName }: DownloadButtonProps) {
  return (
    <a
      href={href}
      download={fileName}
      style={{
        display: "inline-block",
        padding: "0.4rem 0.75rem",
        backgroundColor: "var(--f8-accent)",
        color: "#fff",
        borderRadius: "0.4rem",
        fontSize: "0.85rem",
        fontWeight: 600,
        textDecoration: "none",
      }}
    >
      {label}
    </a>
  );
}