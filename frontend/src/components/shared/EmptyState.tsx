import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 p-8 text-center", className)}>
      {icon && <div className="text-gray-300 w-10 h-10">{icon}</div>}
      <div className="space-y-1">
        <p className="font-medium text-gray-700">{title}</p>
        {description && <p className="text-sm text-gray-400">{description}</p>}
      </div>
      {action && (
        <button
          onClick={action.onClick}
          className="mt-2 px-4 py-1.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
