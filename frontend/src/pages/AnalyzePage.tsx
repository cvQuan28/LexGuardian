import { useState, useEffect, useCallback } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Shield, FileText, ChevronRight, RefreshCw, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { RiskReport } from "@/components/analyze/RiskReport";
import { RiskReportSkeleton } from "@/components/analyze/RiskReportSkeleton";
import { SourceViewer } from "@/components/ask/SourceViewer";
import { useDocuments } from "@/hooks/useDocuments";
import { useWorkspace } from "@/hooks/useWorkspaces";
import { useRiskAnalysis } from "@/hooks/useRiskAnalysis";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { Document, ContractRiskReport } from "@/types";

// Friendly processing messages — no technical internals
const PROCESSING_STEPS = [
  "Đang đọc hợp đồng...",
  "Xác định các bên liên quan...",
  "Phân tích các điều khoản...",
  "Kiểm tra rủi ro pháp lý...",
  "Đối chiếu với quy định hiện hành...",
  "Hoàn thiện báo cáo...",
];

function ProcessingState({ documentName }: { documentName: string }) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStepIndex((p) => (p + 1) % PROCESSING_STEPS.length);
    }, 2800);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center flex-1 py-24 px-4 text-center">
      {/* Animated shield */}
      <div className="relative mb-8">
        <div className="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center">
          <Shield className="w-10 h-10 text-primary animate-pulse" />
        </div>
        <div className="absolute -bottom-1 -right-1 w-6 h-6 bg-white rounded-full flex items-center justify-center shadow-sm border border-gray-100">
          <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
        </div>
      </div>

      <p className="text-lg font-semibold text-gray-800 mb-1">
        Đang phân tích hợp đồng
      </p>
      <p className="text-sm text-gray-500 mb-6 max-w-xs truncate">
        {documentName}
      </p>

      {/* Step indicator */}
      <div className="h-8 flex items-center justify-center">
        <p
          key={stepIndex}
          className="text-sm text-primary/70 font-medium transition-all animate-fade-in"
        >
          {PROCESSING_STEPS[stepIndex]}
        </p>
      </div>

      {/* Progress dots */}
      <div className="flex gap-1.5 mt-6">
        {PROCESSING_STEPS.map((_, i) => (
          <div
            key={i}
            className={cn(
              "w-1.5 h-1.5 rounded-full transition-all duration-500",
              i === stepIndex ? "bg-primary w-4" : "bg-gray-200"
            )}
          />
        ))}
      </div>
    </div>
  );
}

function DocumentPicker({
  documents,
  onSelect,
}: {
  documents: Document[];
  onSelect: (doc: Document) => void;
}) {
  const indexed = documents.filter((d) => d.status === "indexed");
  const others = documents.filter((d) => d.status !== "indexed");

  if (documents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <FileText className="w-10 h-10 text-gray-200 mb-3" />
        <p className="text-sm font-medium text-gray-500">Chưa có tài liệu nào</p>
        <p className="text-xs text-gray-400 mt-1">
          Tải tài liệu lên trong phần Thư viện trước khi phân tích
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-lg mx-auto w-full">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary/10 mb-4">
          <Shield className="w-7 h-7 text-primary" />
        </div>
        <h2 className="text-xl font-semibold text-gray-800">Phân tích rủi ro hợp đồng</h2>
        <p className="text-sm text-gray-500 mt-1.5">
          Chọn tài liệu để phân tích điều khoản và phát hiện rủi ro pháp lý
        </p>
      </div>

      {indexed.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide px-1 mb-2">
            Sẵn sàng phân tích
          </p>
          {indexed.map((doc) => (
            <button
              key={doc.id}
              onClick={() => onSelect(doc)}
              className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl border border-gray-100 bg-white hover:border-primary/30 hover:bg-primary/5 hover:shadow-sm transition-all group text-left"
            >
              <div className="w-9 h-9 rounded-lg bg-gray-100 group-hover:bg-primary/10 flex items-center justify-center flex-shrink-0 transition-colors">
                <FileText className="w-4 h-4 text-gray-400 group-hover:text-primary transition-colors" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">
                  {doc.original_filename || doc.filename}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {doc.page_count ? `${doc.page_count} trang` : ""}{" "}
                  {doc.chunk_count > 0 ? `• ${doc.chunk_count} đoạn` : ""}
                </p>
              </div>
              <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-primary transition-colors flex-shrink-0" />
            </button>
          ))}
        </div>
      ) : null}

      {others.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide px-1 mb-2">
            Đang xử lý
          </p>
          {others.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-3 px-4 py-3.5 rounded-xl border border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
            >
              <div className="w-9 h-9 rounded-lg bg-gray-200 flex items-center justify-center flex-shrink-0">
                <FileText className="w-4 h-4 text-gray-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-600 truncate">
                  {doc.original_filename || doc.filename}
                </p>
                <p className="text-xs text-gray-400 mt-0.5 capitalize">{doc.status}...</p>
              </div>
              <Loader2 className="w-4 h-4 text-gray-300 animate-spin flex-shrink-0" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AnalyzePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [searchParams] = useSearchParams();
  const initialDocId = searchParams.get("documentId");

  const wsId = workspaceId ?? "";
  const { data: workspace } = useWorkspace(wsId ? Number(wsId) : null);
  const { data: documents = [], isLoading: docsLoading } = useDocuments(
    wsId ? Number(wsId) : null
  );

  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const openCitation = useWorkspaceStore((s) => s.openCitation);
  const closeSourceViewer = useWorkspaceStore((s) => s.closeSourceViewer);
  const sourceViewer = useWorkspaceStore((s) => s.sourceViewer);

  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [report, setReport] = useState<ContractRiskReport | null>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const analysisMutation = useRiskAnalysis(wsId ? Number(wsId) : null);

  // Sync workspace to store
  useEffect(() => {
    if (workspace) setActiveWorkspace(workspace);
  }, [workspace, setActiveWorkspace]);

  // Auto-select doc from URL param
  useEffect(() => {
    if (initialDocId && documents.length > 0 && !selectedDoc) {
      const found = documents.find((d) => d.id === Number(initialDocId));
      if (found) setSelectedDoc(found);
    }
  }, [initialDocId, documents, selectedDoc]);

  // Auto-trigger analysis when doc selected
  useEffect(() => {
    if (selectedDoc && !report && !analysisMutation.isPending && !analyzeError) {
      handleAnalyze(selectedDoc);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDoc]);

  const handleAnalyze = useCallback(
    async (doc: Document) => {
      setAnalyzeError(null);
      setReport(null);
      try {
        const result = await analysisMutation.mutateAsync({
          document_id: doc.id,
          document_name: doc.original_filename || doc.filename,
        });
        setReport(result);
        const highCount = result.risk_counts?.high ?? result.risks.filter(r => r.risk_level.toLowerCase() === "high" || r.risk_level.toLowerCase() === "critical").length;
        toast.success(`Phân tích hoàn tất. ${result.risks.length} rủi ro phát hiện${highCount > 0 ? ` (${highCount} nghiêm trọng)` : ""}.`);
      } catch (err) {
        setAnalyzeError(
          err instanceof Error ? err.message : "Phân tích thất bại. Vui lòng thử lại."
        );
      }
    },
    [analysisMutation]
  );

  const handleViewClause = useCallback(
    (clauseRef: string, description: string) => {
      if (!selectedDoc) return;
      // We open the source viewer by constructing a synthetic ChatSourceChunk
      openCitation(
        {
          index: 0,
          chunk_id: clauseRef,
          content: description,
          document_id: selectedDoc.id,
          page_no: 1,
          heading_path: [clauseRef],
          score: 1,
          source_label: clauseRef,
        },
        documents
      );
    },
    [selectedDoc, documents, openCitation]
  );

  const handleRetry = useCallback(() => {
    if (selectedDoc) {
      setAnalyzeError(null);
      setReport(null);
      handleAnalyze(selectedDoc);
    }
  }, [selectedDoc, handleAnalyze]);

  const handleReset = useCallback(() => {
    setSelectedDoc(null);
    setReport(null);
    setAnalyzeError(null);
    analysisMutation.reset();
  }, [analysisMutation]);

  const isViewerOpen = sourceViewer.open && sourceViewer.document != null;
  const isAnalyzing = analysisMutation.isPending;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main panel */}
      <div
        className={cn(
          "flex flex-col h-full transition-all duration-300",
          isViewerOpen ? "w-[55%] border-r border-gray-100" : "w-full"
        )}
      >
        {/* Top bar */}
        <div className="flex items-center gap-3 px-5 py-3.5 border-b border-gray-100 bg-white flex-shrink-0">
          <Shield className="w-4.5 h-4.5 text-primary flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <h1 className="text-sm font-semibold text-gray-800">
              Phân tích Rủi ro
            </h1>
            {workspace && (
              <p className="text-xs text-gray-400 truncate">{workspace.name}</p>
            )}
          </div>
          {(selectedDoc || report) && (
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              <RefreshCw className="w-3 h-3" />
              Tài liệu khác
            </button>
          )}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-6">
          {/* Loading documents */}
          {docsLoading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-5 h-5 animate-spin text-gray-300" />
            </div>
          )}

          {/* Document picker */}
          {!docsLoading && !selectedDoc && !isAnalyzing && !report && (
            <DocumentPicker
              documents={documents}
              onSelect={(doc) => setSelectedDoc(doc)}
            />
          )}

          {/* Processing state */}
          {isAnalyzing && selectedDoc && (
            <ProcessingState
              documentName={selectedDoc.original_filename || selectedDoc.filename}
            />
          )}

          {/* Error state */}
          {analyzeError && !isAnalyzing && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <AlertCircle className="w-10 h-10 text-red-300 mb-4" />
              <p className="text-sm font-medium text-gray-700 mb-1">
                Phân tích thất bại
              </p>
              <p className="text-xs text-gray-400 mb-5 max-w-xs">{analyzeError}</p>
              <button
                onClick={handleRetry}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Thử lại
              </button>
            </div>
          )}

          {/* Risk report */}
          {report && !isAnalyzing && (
            <div className="max-w-2xl mx-auto">
              <RiskReport report={report} onViewClause={handleViewClause} />
            </div>
          )}

          {/* Skeleton while analyzing but no report yet (shouldn't happen but safety) */}
          {isAnalyzing && !selectedDoc && <RiskReportSkeleton />}
        </div>
      </div>

      {/* Source Viewer panel */}
      <div
        className={cn(
          "flex-shrink-0 transition-all duration-300 overflow-hidden",
          isViewerOpen ? "w-[45%]" : "w-0"
        )}
      >
        {isViewerOpen && sourceViewer.document && (
          <SourceViewer
            doc={sourceViewer.document}
            scrollToPage={sourceViewer.scrollToPage}
            scrollToHeading={sourceViewer.scrollToHeading ?? undefined}
            highlightText={sourceViewer.highlightText ?? undefined}
            onClose={closeSourceViewer}
          />
        )}
      </div>
    </div>
  );
}
