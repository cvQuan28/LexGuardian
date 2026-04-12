import { useRef, useCallback, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  Upload,
  Trash2,
  FileText,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/shared/EmptyState";
import { useDocuments, useUploadDocument, useDeleteDocument } from "@/hooks/useDocuments";
import { useWorkspace } from "@/hooks/useWorkspaces";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { formatFileSize, formatDate } from "@/lib/utils";
import type { Document, DocumentStatus } from "@/types";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: DocumentStatus }) {
  const config: Record<DocumentStatus, { label: string; className: string; icon: React.ElementType; pulse?: boolean }> = {
    pending: {
      label: "Pending",
      className: "bg-gray-100 text-gray-500 border-gray-200",
      icon: Clock,
    },
    parsing: {
      label: "Parsing",
      className: "bg-blue-50 text-blue-600 border-blue-200",
      icon: RefreshCw,
      pulse: true,
    },
    indexing: {
      label: "Indexing",
      className: "bg-blue-50 text-blue-600 border-blue-200",
      icon: RefreshCw,
      pulse: true,
    },
    processing: {
      label: "Processing",
      className: "bg-blue-50 text-blue-600 border-blue-200",
      icon: RefreshCw,
      pulse: true,
    },
    indexed: {
      label: "Ready",
      className: "bg-emerald-50 text-emerald-600 border-emerald-200",
      icon: CheckCircle2,
    },
    failed: {
      label: "Failed",
      className: "bg-red-50 text-red-600 border-red-200",
      icon: AlertCircle,
    },
  };

  const cfg = config[status] ?? config.pending;
  const Icon = cfg.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border",
        cfg.className,
        cfg.pulse && "animate-pulse"
      )}
    >
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Document row
// ---------------------------------------------------------------------------
interface DocumentRowProps {
  doc: Document;
  onDelete: (doc: Document) => void;
  isDeleting: boolean;
}

function DocumentRow({ doc, onDelete, isDeleting }: DocumentRowProps) {
  return (
    <div className="flex items-center gap-4 px-4 py-3 rounded-xl bg-white border border-gray-100 hover:border-gray-200 hover:shadow-sm transition-all group">
      {/* File icon */}
      <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
        <FileText className="w-4 h-4 text-primary/60" />
      </div>

      {/* File info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate" title={doc.original_filename}>
          {doc.original_filename}
        </p>
        <p className="text-xs text-gray-400 mt-0.5">
          {formatFileSize(doc.file_size)} • {formatDate(doc.created_at)}
          {doc.page_count ? ` • ${doc.page_count} trang` : ""}
          {doc.chunk_count > 0 ? ` • ${doc.chunk_count} chunks` : ""}
        </p>
        {doc.error_message && (
          <p className="text-xs text-red-500 mt-0.5 truncate" title={doc.error_message}>
            {doc.error_message}
          </p>
        )}
      </div>

      {/* Status */}
      <div className="flex-shrink-0">
        <StatusBadge status={doc.status} />
      </div>

      {/* Delete button */}
      <button
        onClick={() => onDelete(doc)}
        disabled={isDeleting}
        className="flex-shrink-0 p-1.5 rounded-md text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
        aria-label="Delete document"
      >
        {isDeleting ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Trash2 className="w-4 h-4" />
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LibraryPage
// ---------------------------------------------------------------------------
export function LibraryPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const wsId = workspaceId ? Number(workspaceId) : null;

  const { data: workspace } = useWorkspace(wsId);
  const { data: documents = [], isLoading, refetch } = useDocuments(wsId);
  const uploadMutation = useUploadDocument(wsId ?? 0);
  const deleteMutation = useDeleteDocument();

  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (workspace) setActiveWorkspace(workspace);
  }, [workspace, setActiveWorkspace]);

  // Auto-refresh while documents are processing
  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.status === "parsing" || d.status === "indexing" || d.status === "processing"
    );
    if (!hasProcessing) return;
    const interval = setInterval(() => refetch(), 3000);
    return () => clearInterval(interval);
  }, [documents, refetch]);

  const handleFileInputChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      for (const file of files) {
        try {
          await uploadMutation.mutateAsync(file);
        } catch {
          // Error handled by mutation
        }
      }
      // Reset input
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [uploadMutation]
  );

  const handleDelete = useCallback(
    async (doc: Document) => {
      if (!wsId) return;
      if (!confirm(`Xóa "${doc.original_filename}"?`)) return;
      try {
        await deleteMutation.mutateAsync({ docId: doc.id, workspaceId: wsId });
      } catch {
        // Error handled by mutation
      }
    },
    [deleteMutation, wsId]
  );

  const isDeletingId = deleteMutation.isPending ? deleteMutation.variables?.docId : null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-white flex-shrink-0">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Thư viện tài liệu</h1>
          {workspace && (
            <p className="text-xs text-gray-400 mt-0.5">
              {workspace.name} • {workspace.document_count} tài liệu
              {workspace.indexed_count !== workspace.document_count && (
                <span className="ml-1 text-blue-500">
                  ({workspace.indexed_count} đã index)
                </span>
              )}
            </p>
          )}
        </div>

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60"
        >
          {uploadMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Upload className="w-4 h-4" />
          )}
          Tải lên PDF
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          className="hidden"
          onChange={handleFileInputChange}
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-5 h-5 animate-spin text-gray-300" />
          </div>
        ) : documents.length === 0 ? (
          <EmptyState
            icon={<FileText className="w-10 h-10" />}
            title="Chưa có tài liệu nào"
            description="Tải lên hợp đồng hoặc tài liệu pháp lý đầu tiên của bạn"
            action={{
              label: "Tải lên PDF",
              onClick: () => fileInputRef.current?.click(),
            }}
            className="py-20"
          />
        ) : (
          <div className="space-y-2 max-w-3xl">
            {documents.map((doc) => (
              <DocumentRow
                key={doc.id}
                doc={doc}
                onDelete={handleDelete}
                isDeleting={isDeletingId === doc.id}
              />
            ))}
          </div>
        )}

        {/* Upload progress */}
        {uploadMutation.isPending && (
          <div className="mt-3 max-w-3xl">
            <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-blue-50 border border-blue-100">
              <Loader2 className="w-4 h-4 animate-spin text-blue-500 flex-shrink-0" />
              <p className="text-sm text-blue-600">Đang tải lên và xử lý tài liệu...</p>
            </div>
          </div>
        )}

        {/* Upload error */}
        {uploadMutation.isError && (
          <div className="mt-3 max-w-3xl">
            <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-50 border border-red-100">
              <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
              <p className="text-sm text-red-600">
                {(uploadMutation.error as Error)?.message || "Upload thất bại"}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
