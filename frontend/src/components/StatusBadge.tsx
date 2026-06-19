import { Badge, type BadgeProps } from "./ui/badge";
import { useLang } from "../lib/i18n";

const VARIANT: Record<string, BadgeProps["variant"]> = {
  queued: "default",
  running: "info",
  awaiting_approval: "warn",
  completed: "good",
  finished: "good",
  error: "danger",
  cancelled: "default",
  idle: "default",
  connecting: "info",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useLang();
  const key = status?.toLowerCase?.() ?? "idle";
  const variant = VARIANT[key] ?? "default";
  const label = t(`status.${key}`);
  return (
    <Badge variant={variant}>
      {label === `status.${key}` ? status : label}
    </Badge>
  );
}
