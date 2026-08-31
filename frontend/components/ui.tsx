import type { ReactNode } from "react";
import { Activity, Check, Cloud, FlaskConical, ShieldAlert } from "lucide-react";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function SourceBadge({ live, cloudSource = false }: { live: boolean; cloudSource?: boolean }) {
  if (cloudSource && !live) {
    return <Badge tone="cyan"><Cloud size={12} />GOOGLE CLOUD SOURCE</Badge>;
  }
  return (
    <Badge tone={live ? "live" : "demo"}>
      {live ? <Cloud size={12} /> : <FlaskConical size={12} />}
      {live ? "LIVE GOOGLE CLOUD" : "DEMO CONNECTOR"}
    </Badge>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const lower = value.toLowerCase();
  const tone = lower.includes("not_connected") || lower.includes("not connected")
    ? "neutral"
    : lower.includes("deny") || lower.includes("block") || lower.includes("fail")
    ? "danger"
    : lower.includes("wait") || lower.includes("unverified") || lower.includes("config")
      ? "warning"
      : lower.includes("closed") || lower.includes("verified") || lower.includes("approved") || lower.includes("connected") || lower.includes("healthy") || lower.includes("ready")
        ? "success"
        : "neutral";
  return <Badge tone={tone}>{value.replaceAll("_", " ")}</Badge>;
}

export function Empty({ icon = "activity", title, detail }: { icon?: "activity" | "shield"; title: string; detail: string }) {
  return (
    <div className="empty-state">
      {icon === "shield" ? <ShieldAlert size={24} /> : <Activity size={24} />}
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

export function CheckRow({ children }: { children: ReactNode }) {
  return <div className="check-row"><span><Check size={13} /></span>{children}</div>;
}

export function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
