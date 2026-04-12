import { Shield, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { RiskScorePill } from "./RiskBadge";
import type { RiskCounts } from "@/types";

interface RiskScorecardProps {
  documentName: string;
  overallRiskLevel: string;
  riskCounts: RiskCounts;
  summary: string;
  partiesIdentified: string[];
  governingLaw: string;
}

function SeverityCount({
  count,
  label,
  colorClass,
}: {
  count: number;
  label: string;
  colorClass: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className={cn("text-2xl font-bold tabular-nums", colorClass)}>
        {count}
      </span>
      <span className="text-[11px] text-gray-500 font-medium">{label}</span>
    </div>
  );
}

export function RiskScorecard({
  documentName,
  overallRiskLevel,
  riskCounts,
  summary,
  partiesIdentified,
  governingLaw,
}: RiskScorecardProps) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      {/* Header band */}
      <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-gray-50">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
            <Shield className="w-4.5 h-4.5 text-primary" />
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Báo cáo phân tích</p>
            <h2 className="text-sm font-semibold text-gray-900 leading-tight max-w-xs truncate">
              {documentName || "Hợp đồng"}
            </h2>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <RiskScorePill level={overallRiskLevel} />
          <button
            type="button"
            disabled
            title="Xuất báo cáo (sắp có)"
            className="p-1.5 rounded-lg text-gray-300 cursor-not-allowed"
          >
            <Download className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Count row */}
      <div className="grid grid-cols-3 divide-x divide-gray-50 px-5 py-4">
        <SeverityCount
          count={riskCounts.high}
          label="Nghiêm trọng"
          colorClass="text-red-600"
        />
        <SeverityCount
          count={riskCounts.medium}
          label="Trung bình"
          colorClass="text-amber-600"
        />
        <SeverityCount
          count={riskCounts.low}
          label="Thấp"
          colorClass="text-blue-600"
        />
      </div>

      {/* Summary */}
      {summary && (
        <div className="px-5 pb-4 border-t border-gray-50">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-3 mb-1.5">
            Tóm tắt
          </p>
          <p className="text-sm text-gray-600 leading-relaxed">{summary}</p>
        </div>
      )}

      {/* Meta info */}
      {(partiesIdentified.length > 0 || governingLaw) && (
        <div className="px-5 pb-4 flex flex-wrap gap-4 text-xs text-gray-500">
          {partiesIdentified.length > 0 && (
            <span>
              <span className="font-medium text-gray-600">Các bên: </span>
              {partiesIdentified.join(", ")}
            </span>
          )}
          {governingLaw && (
            <span>
              <span className="font-medium text-gray-600">Luật áp dụng: </span>
              {governingLaw}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
