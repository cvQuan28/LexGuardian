import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "secondary" | "outline" | "critical" | "medium" | "low" | "info";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: "bg-primary text-primary-foreground",
  secondary: "bg-surface-mid text-foreground/80",
  outline: "border border-current bg-transparent",
  critical: "bg-red-50 text-red-700 border border-red-200",
  medium: "bg-amber-50 text-amber-700 border border-amber-200",
  low: "bg-blue-50 text-blue-700 border border-blue-200",
  info: "bg-gray-50 text-gray-600 border border-gray-200",
};

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
        variantClasses[variant],
        className
      )}
      {...props}
    />
  );
}
