import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ContractRiskReport } from "@/types";

interface RiskAnalysisRequest {
  document_id: number;
  document_name?: string;
}

export function useRiskAnalysis(workspaceId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: RiskAnalysisRequest) =>
      api.post<ContractRiskReport>(
        `/legal/analyze-risk/${workspaceId}`,
        req
      ),
    onSuccess: (data) => {
      // Cache result by document_id for quick re-access
      qc.setQueryData(
        ["risk-report", workspaceId, data.document_id],
        data
      );
    },
  });
}
