import { useState } from "react";
import { ChevronDown, BookOpen, AlertTriangle, Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";
import { RiskBadge } from "./RiskBadge";
import type { LegalRiskItem } from "@/types";

interface RiskItemProps {
  item: LegalRiskItem;
  onViewClause?: (clauseRef: string, description: string) => void;
  defaultExpanded?: boolean;
  index?: number;
}

function formatRiskType(riskType: string): string {
  return riskType
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function RiskItem({ item, onViewClause, defaultExpanded = false, index }: RiskItemProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div
      className={cn(
        "rounded-xl border overflow-hidden transition-shadow",
        expanded ? "shadow-sm" : "shadow-none",
        item.risk_level.toLowerCase() === "high" || item.risk_level.toLowerCase() === "critical"
          ? "border-red-100"
          : item.risk_level.toLowerCase() === "medium"
          ? "border-amber-100"
          : "border-blue-100"
      )}
    >
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className={cn(
          "w-full flex items-center gap-3 px-4 py-3.5 text-left transition-colors",
          expanded
            ? item.risk_level.toLowerCase() === "high" || item.risk_level.toLowerCase() === "critical"
              ? "bg-red-50"
              : item.risk_level.toLowerCase() === "medium"
              ? "bg-amber-50"
              : "bg-blue-50"
            : "bg-white hover:bg-gray-50"
        )}
      >
        {/* Index number */}
        {index !== undefined && (
          <span className="text-xs font-mono text-gray-400 w-5 flex-shrink-0 text-center">
            {index + 1}
          </span>
        )}

        {/* Risk badge */}
        <RiskBadge severity={item.risk_level} className="flex-shrink-0" />

        {/* Title */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-800 truncate">
            {formatRiskType(item.risk_type)}
          </p>
          <p className="text-xs text-gray-500 truncate mt-0.5">
            {item.clause_reference}
          </p>
        </div>

        {/* Chevron */}
        <ChevronDown
          className={cn(
            "w-4 h-4 text-gray-400 flex-shrink-0 transition-transform duration-200",
            expanded && "rotate-180"
          )}
        />
      </button>

      {/* Body — expanded */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 bg-white space-y-4 border-t border-gray-50">
          {/* Description */}
          <div className="flex gap-2.5 mt-3">
            <AlertTriangle className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
                Phân tích
              </p>
              <p className="text-sm text-gray-700 leading-relaxed">
                {item.description}
              </p>
            </div>
          </div>

          {/* Recommendation */}
          {item.recommendation && (
            <div className="flex gap-2.5">
              <Lightbulb className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Đề xuất
                </p>
                <p className="text-sm text-gray-700 leading-relaxed">
                  {item.recommendation}
                </p>
              </div>
            </div>
          )}

          {/* Clause reference + view button */}
          <div className="flex items-center justify-between pt-1">
            <span className="inline-flex items-center gap-1.5 text-xs text-gray-400 font-mono bg-gray-50 px-2.5 py-1 rounded-lg border border-gray-100">
              {item.clause_reference}
            </span>
            {onViewClause && (
              <button
                type="button"
                onClick={() => onViewClause(item.clause_reference, item.description)}
                className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
              >
                <BookOpen className="w-3.5 h-3.5" />
                Xem điều khoản gốc
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
