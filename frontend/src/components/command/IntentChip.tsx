import type { IntentType } from "@/types";
import { cn } from "@/lib/utils";
import { FileSearch, Search, AlertTriangle, CheckCircle, MessageSquare } from "lucide-react";

const INTENT_CONFIG = {
  ASK_DOCUMENT: { label: "Hỏi hợp đồng", icon: FileSearch, color: "bg-blue-50 text-blue-700 border-blue-200" },
  ASK_LAW: { label: "Tra cứu luật", icon: Search, color: "bg-purple-50 text-purple-700 border-purple-200" },
  ANALYZE_RISK: { label: "Phân tích rủi ro", icon: AlertTriangle, color: "bg-amber-50 text-amber-700 border-amber-200" },
  CHECK_VALIDITY: { label: "Kiểm tra hiệu lực", icon: CheckCircle, color: "bg-green-50 text-green-700 border-green-200" },
  GENERAL: { label: "Câu hỏi chung", icon: MessageSquare, color: "bg-gray-50 text-gray-600 border-gray-200" },
};

interface IntentChipProps {
  intent: IntentType;
  confidence?: number;
  className?: string;
}

export function IntentChip({ intent, confidence, className }: IntentChipProps) {
  const cfg = INTENT_CONFIG[intent];
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border",
        cfg.color,
        className
      )}
    >
      <Icon className="w-3 h-3" />
      {cfg.label}
      {confidence !== undefined && (
        <span className="opacity-60 font-mono">({Math.round(confidence * 100)}%)</span>
      )}
    </span>
  );
}
