import { useMemo } from "react";
import { AlertCircle, CheckCircle2, Zap, ShieldCheck } from "lucide-react";
import { RiskScorecard } from "./RiskScorecard";
import { RiskItem } from "./RiskItem";
import type { ContractRiskReport, LegalRiskItem } from "@/types";

interface RiskReportProps {
  report: ContractRiskReport;
  onViewClause?: (clauseRef: string, description: string) => void;
}

function severityOrder(level: string): number {
  const l = level.toLowerCase();
  if (l === "critical" || l === "high") return 0;
  if (l === "medium") return 1;
  return 2;
}

export function RiskReport({ report, onViewClause }: RiskReportProps) {
  const sortedRisks = useMemo<LegalRiskItem[]>(() => {
    return [...report.risks].sort(
      (a, b) => severityOrder(a.risk_level) - severityOrder(b.risk_level)
    );
  }, [report.risks]);

  const riskCounts = report.risk_counts ?? {
    high: report.risks.filter(
      (r) => r.risk_level.toLowerCase() === "high" || r.risk_level.toLowerCase() === "critical"
    ).length,
    medium: report.risks.filter((r) => r.risk_level.toLowerCase() === "medium").length,
    low: report.risks.filter((r) => r.risk_level.toLowerCase() === "low").length,
    total: report.risks.length,
  };

  return (
    <div className="space-y-5">
      {/* Scorecard */}
      <RiskScorecard
        documentName={report.document_name}
        overallRiskLevel={report.overall_risk_level}
        riskCounts={riskCounts}
        summary={report.summary}
        partiesIdentified={report.parties_identified}
        governingLaw={report.governing_law}
      />

      {/* Zero-risk success state */}
      {sortedRisks.length === 0 && (report.missing_clauses ?? []).length === 0 && (
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <div className="w-14 h-14 rounded-2xl bg-emerald-50 flex items-center justify-center">
            <ShieldCheck className="w-7 h-7 text-emerald-500" />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-800 mb-1">Hợp đồng không có rủi ro đáng kể</p>
            <p className="text-xs text-gray-400 max-w-xs leading-relaxed">
              Hệ thống không phát hiện điều khoản bất lợi nào. Tuy nhiên vẫn nên tham khảo ý kiến chuyên gia pháp lý trước khi ký.
            </p>
          </div>
        </div>
      )}

      {/* Risk Items */}
      {sortedRisks.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <AlertCircle className="w-4 h-4 text-gray-400" />
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Rủi ro phát hiện ({sortedRisks.length})
            </h3>
          </div>
          <div className="space-y-2">
            {sortedRisks.map((item, i) => (
              <RiskItem
                key={item.clause_id || `${i}`}
                item={item}
                index={i}
                onViewClause={onViewClause}
                defaultExpanded={i === 0}
              />
            ))}
          </div>
        </div>
      )}

      {/* Missing Standard Clauses */}
      {report.missing_clauses.length > 0 && (
        <div className="bg-amber-50 border border-amber-100 rounded-xl px-4 py-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <h3 className="text-xs font-semibold text-amber-700 uppercase tracking-wide">
              Thiếu điều khoản tiêu chuẩn ({report.missing_clauses.length})
            </h3>
          </div>
          <ul className="space-y-1.5">
            {report.missing_clauses.map((clause, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-amber-800">
                <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
                {clause}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recommended Actions */}
      {report.recommended_actions && report.recommended_actions.length > 0 && (
        <div className="bg-white border border-gray-100 rounded-xl px-4 py-4 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-primary" />
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
              Hành động đề xuất
            </h3>
          </div>
          <ol className="space-y-2">
            {report.recommended_actions.map((action, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="w-5 h-5 rounded-full bg-primary/10 text-primary text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                  {i + 1}
                </span>
                <div>
                  <p className="text-sm font-medium text-gray-800">{action.label}</p>
                  {action.description && (
                    <p className="text-xs text-gray-500 mt-0.5">{action.description}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* All clear */}
      {sortedRisks.length === 0 && report.missing_clauses.length === 0 && (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <CheckCircle2 className="w-10 h-10 text-green-400 mb-3" />
          <p className="text-sm font-medium text-gray-600">
            Không phát hiện rủi ro nghiêm trọng
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Hợp đồng này có vẻ phù hợp với các tiêu chuẩn pháp lý cơ bản
          </p>
        </div>
      )}
    </div>
  );
}
