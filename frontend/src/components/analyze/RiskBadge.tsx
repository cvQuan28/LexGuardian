import { cn } from "@/lib/utils";
import type { RiskSeverity } from "@/types";

interface RiskBadgeProps {
  severity: RiskSeverity | string;
  className?: string;
  size?: "sm" | "md";
}

function normalize(severity: string): "high" | "medium" | "low" {
  const s = severity.toLowerCase();
  if (s === "critical" || s === "high") return "high";
  if (s === "medium") return "medium";
  return "low";
}

const VARIANT_MAP = {
  high: {
    label: "Nghiêm trọng",
    className: "bg-red-50 text-red-700 border-red-200",
    dot: "bg-red-500",
  },
  medium: {
    label: "Trung bình",
    className: "bg-amber-50 text-amber-700 border-amber-200",
    dot: "bg-amber-500",
  },
  low: {
    label: "Thấp",
    className: "bg-blue-50 text-blue-700 border-blue-200",
    dot: "bg-blue-400",
  },
} as const;

export function RiskBadge({ severity, className, size = "sm" }: RiskBadgeProps) {
  const level = normalize(severity);
  const variant = VARIANT_MAP[level];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs",
        variant.className,
        className
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", variant.dot)} />
      {variant.label}
    </span>
  );
}

// For overall risk score (larger display)
export function RiskScorePill({ level }: { level: string }) {
  const normalized = normalize(level);
  const configs = {
    high: { label: "RỦI RO CAO", className: "bg-red-600 text-white" },
    medium: { label: "RỦI RO TRUNG BÌNH", className: "bg-amber-500 text-white" },
    low: { label: "RỦI RO THẤP", className: "bg-blue-500 text-white" },
  };
  const config = configs[normalized];
  return (
    <span className={cn("inline-flex items-center px-3 py-1 rounded-full text-xs font-bold tracking-wide", config.className)}>
      {config.label}
    </span>
  );
}
