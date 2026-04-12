import { useRef, useCallback, useEffect, useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Upload, Trash2, FileText, Loader2, AlertCircle, CheckCircle2,
  Clock, RefreshCw, Search, X, Shield, ChevronRight, CheckSquare, Square,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/shared/EmptyState";
import { useDocuments, useUploadDocument, useDeleteDocument } from "@/hooks/useDocuments";
import { useWorkspace } from "@/hooks/useWorkspaces";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { formatFileSize, formatDate } from "@/lib/utils";
import type { Document, DocumentStatus } from "@/types";

// ---------------------------------------------------------------------------
// Status badge — product language only, no technical terms
// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: DocumentStatus }) {
  const config: Record<DocumentStatus, { label: string; className: string; icon: React.ElementType; pulse?: boolean }> = {
    pending:    { label: "Đang chờ",    className: "bg-gray-100 text-gray-500 border-gray-200",    icon: Clock },
    parsing:    { label: "Đang xử lý", className: "bg-blue-50 text-blue-600 border-blue-200",     icon: RefreshCw, pulse: true },
    indexing:   { label: "Đang xử lý", className: "bg-blue-50 text-blue-600 border-blue-200",     icon: RefreshCw, pulse: true },
    processing: { label: "Đang xử lý", className: "bg-blue-50 text-blue-600 border-blue-200",     icon: RefreshCw, pulse: true },
    indexed:    { label: "Sẵn sàng",   className: "bg-emerald-50 text-emerald-600 border-emerald-200", icon: CheckCircle2 },
    failed:     { label: "Thất bại",   className: "bg-red-50 text-red-600 border-red-200",        icon: AlertCircle },
  };
  const cfg = config[status] ?? config.pending;
  const Icon = cfg.icon;
  return (
    <span className={cn(
      "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border",
      cfg.className, cfg.pulse && "animate-pulse"
    )}>
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
  selected: boolean;
  onSelect: (id: number) => void;
  onDelete: (doc: Document) => void;
  onAnalyze: (doc: Document) => void;
  onViewSource: (doc: Document) => void;
  isDeleting: boolean;
}

function DocumentRow({ doc, selected, onSelect, onDelete, onAnalyze, onViewSource, isDeleting }: DocumentRowProps) {
  const isIndexed = doc.status === "indexed";
  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-3 rounded-xl border transition-all group",
        selected
          ? "bg-primary/5 border-primary/20"
          : "bg-white border-gray-100 hover:border-gray-200 hover:shadow-sm"
      )}
    >
      {/* Checkbox */}
      <button
        type="button"
        onClick={() => onSelect(doc.id)}
        className="flex-shrink-0 text-gray-300 hover:text-primary transition-colors"
        aria-label={selected ? "Bỏ chọn" : "Chọn"}
      >
        {selected
          ? <CheckSquare className="w-4 h-4 text-primary" />
          : <Square className="w-4 h-4" />
        }
      </button>

      {/* File icon */}
      <div
        className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 cursor-pointer"
        onClick={() => isIndexed && onViewSource(doc)}
        title={isIndexed ? "Xem tài liệu" : undefined}
      >
        <FileText className="w-4 h-4 text-primary/60" />
      </div>

      {/* File info */}
      <div
        className={cn("flex-1 min-w-0", isIndexed && "cursor-pointer")}
        onClick={() => isIndexed && onViewSource(doc)}
      >
        <p className="text-sm font-medium text-gray-800 truncate" title={doc.original_filename}>
          {doc.original_filename}
        </p>
        <p className="text-xs text-gray-400 mt-0.5">
          {formatFileSize(doc.file_size)} • {formatDate(doc.created_at)}
          {doc.page_count ? ` • ${doc.page_count} trang` : ""}
        </p>
        {doc.error_message && (
          <p className="text-xs text-red-500 mt-0.5 truncate" title={doc.error_message}>
            Lỗi xử lý tài liệu
          </p>
        )}
      </div>

      {/* Status */}
      <div className="flex-shrink-0">
        <StatusBadge status={doc.status} />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
        {isIndexed && (
          <>
            <button
              onClick={() => onViewSource(doc)}
              className="p-1.5 rounded-md text-gray-400 hover:text-primary hover:bg-primary/5 transition-colors"
              title="Xem tài liệu"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => onAnalyze(doc)}
              className="p-1.5 rounded-md text-gray-400 hover:text-primary hover:bg-primary/5 transition-colors"
              title="Phân tích rủi ro"
            >
              <Shield className="w-3.5 h-3.5" />
            </button>
          </>
        )}
        <button
          onClick={() => onDelete(doc)}
          disabled={isDeleting}
          className="p-1.5 rounded-md text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors"
          aria-label="Xóa tài liệu"
        >
          {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LibraryPage
// ---------------------------------------------------------------------------
export function LibraryPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();
  const wsId = workspaceId ? Number(workspaceId) : null;

  const { data: workspace } = useWorkspace(wsId);
  const { data: documents = [], isLoading, refetch } = useDocuments(wsId);
  const uploadMutation = useUploadDocument(wsId ?? 0);
  const deleteMutation = useDeleteDocument();

  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const openSourceViewer = useWorkspaceStore((s) => s.openSourceViewer);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Sync workspace to store
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

  // Filtered documents
  const filtered = useMemo(() => {
    if (!search.trim()) return documents;
    const q = search.toLowerCase();
    return documents.filter((d) =>
      (d.original_filename || d.filename).toLowerCase().includes(q)
    );
  }, [documents, search]);

  const handleUpload = useCallback(async (files: File[]) => {
    for (const file of files) {
      try {
        await uploadMutation.mutateAsync(file);
        toast.success(`Đã tải lên "${file.name}". Đang xử lý tài liệu...`);
      } catch (err) {
        toast.error(`Không thể tải lên "${file.name}". Vui lòng thử lại.`);
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [uploadMutation]);

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length) handleUpload(files);
    }, [handleUpload]
  );

  const handleDelete = useCallback(async (doc: Document) => {
    if (!wsId) return;
    if (!confirm(`Xóa "${doc.original_filename}"?`)) return;
    try {
      await deleteMutation.mutateAsync({ docId: doc.id, workspaceId: wsId });
      toast.success(`Đã xóa "${doc.original_filename}"`);
      setSelected((s) => { const n = new Set(s); n.delete(doc.id); return n; });
    } catch {
      toast.error("Không thể xóa tài liệu. Vui lòng thử lại.");
    }
  }, [deleteMutation, wsId]);

  const handleBulkDelete = useCallback(async () => {
    if (!wsId || selected.size === 0) return;
    if (!confirm(`Xóa ${selected.size} tài liệu đã chọn?`)) return;
    let deletedCount = 0;
    for (const docId of selected) {
      try {
        await deleteMutation.mutateAsync({ docId, workspaceId: wsId });
        deletedCount++;
      } catch { /* continue */ }
    }
    toast.success(`Đã xóa ${deletedCount} tài liệu`);
    setSelected(new Set());
  }, [selected, wsId, deleteMutation]);

  const handleSelectToggle = useCallback((id: number) => {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((d) => d.id)));
    }
  }, [selected, filtered]);

  const handleViewSource = useCallback((doc: Document) => {
    openSourceViewer(doc, 1, null, null);
  }, [openSourceViewer]);

  const handleAnalyze = useCallback((doc: Document) => {
    navigate(`/analyze/${wsId}?documentId=${doc.id}`);
  }, [navigate, wsId]);

  const isDeletingId = deleteMutation.isPending ? deleteMutation.variables?.docId : null;
  const allSelected = filtered.length > 0 && selected.size === filtered.length;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-white flex-shrink-0">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Thư viện tài liệu</h1>
          {workspace && (
            <p className="text-xs text-gray-400 mt-0.5">
              {workspace.name} • {workspace.document_count} tài liệu
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={handleBulkDelete}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-50 text-red-600 text-xs font-medium hover:bg-red-100 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Xóa {selected.size}
            </button>
          )}
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
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          multiple
          className="hidden"
          onChange={handleFileInputChange}
        />
      </div>

      {/* Search bar + select-all */}
      {documents.length > 0 && (
        <div className="flex items-center gap-3 px-6 py-3 border-b border-gray-50 bg-white flex-shrink-0">
          <button
            onClick={handleSelectAll}
            className="text-gray-400 hover:text-primary transition-colors"
            title={allSelected ? "Bỏ chọn tất cả" : "Chọn tất cả"}
          >
            {allSelected
              ? <CheckSquare className="w-4 h-4 text-primary" />
              : <Square className="w-4 h-4" />
            }
          </button>
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm tài liệu..."
              className="w-full pl-9 pr-8 py-1.5 rounded-lg border border-gray-200 text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 focus:bg-white transition-colors"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <span className="text-xs text-gray-400">
            {filtered.length} tài liệu{search ? " tìm thấy" : ""}
          </span>
        </div>
      )}

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
            action={{ label: "Tải lên PDF", onClick: () => fileInputRef.current?.click() }}
            className="py-20"
          />
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Search className="w-8 h-8 text-gray-200 mb-3" />
            <p className="text-sm text-gray-500">Không tìm thấy tài liệu nào phù hợp</p>
            <button onClick={() => setSearch("")} className="mt-2 text-xs text-primary hover:underline">
              Xóa bộ lọc
            </button>
          </div>
        ) : (
          <div className="space-y-2 max-w-3xl">
            {filtered.map((doc) => (
              <DocumentRow
                key={doc.id}
                doc={doc}
                selected={selected.has(doc.id)}
                onSelect={handleSelectToggle}
                onDelete={handleDelete}
                onAnalyze={handleAnalyze}
                onViewSource={handleViewSource}
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
      </div>
    </div>
  );
}
