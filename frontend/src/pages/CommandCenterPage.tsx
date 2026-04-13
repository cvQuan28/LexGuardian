import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Scale, FileText, Plus, X, Loader2, Shield, BookOpen, Library, Globe } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { CommandBar } from "@/components/command/CommandBar";
import { EmptyState } from "@/components/shared/EmptyState";
import { useWorkspaces, useCreateWorkspace } from "@/hooks/useWorkspaces";
import { useDetectIntent } from "@/hooks/useCommand";
import { useUploadDocument } from "@/hooks/useDocuments";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { formatDate } from "@/lib/utils";
import type { KnowledgeBase } from "@/types";

type AppMode = "legal" | "document" | "analyze";

export function CommandCenterPage() {
  const navigate = useNavigate();
  const { data: workspaces, isLoading: workspacesLoading } = useWorkspaces();
  const { mutateAsync: createWorkspace, isPending: creatingWorkspace } = useCreateWorkspace();
  const activeWorkspace = useWorkspaceStore((s) => s.activeWorkspace);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);

  const detectIntent = useDetectIntent(activeWorkspace?.id ?? workspaces?.[0]?.id ?? null);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newBriefName, setNewBriefName] = useState("");
  const [commandText, setCommandText] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);

  // File intent modal state
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  const [uploadingFile, setUploadingFile] = useState(false);

  // Upload hook — only active when we have a workspace
  const wsForUpload = activeWorkspace ?? workspaces?.[0];
  const uploadDocument = useUploadDocument(wsForUpload?.id ?? 0);

  const handleBriefClick = useCallback((ws: KnowledgeBase) => {
    setActiveWorkspace(ws);
    navigate(`/ask/${ws.id}`);
  }, [navigate, setActiveWorkspace]);

  const handleCreateBrief = useCallback(async () => {
    const trimmed = newBriefName.trim();
    if (!trimmed) return;
    try {
      const ws = await createWorkspace({ name: trimmed });
      setActiveWorkspace(ws);
      setShowCreateModal(false);
      setNewBriefName("");
      navigate(`/ask/${ws.id}`);
    } catch {
      // Error handled by toast/mutation
    }
  }, [newBriefName, createWorkspace, setActiveWorkspace, navigate]);

  /** Navigate with explicit mode — called from mode cards or command bar Enter */
  const handleNavigateWithMode = useCallback((text: string, mode: AppMode, files?: File[]) => {
    const ws = activeWorkspace ?? workspaces?.[0];
    if (!ws) {
      setShowCreateModal(true);
      return;
    }
    setActiveWorkspace(ws);

    if (files && files.length > 0) {
      navigate(`/library/${ws.id}`);
      return;
    }

    const encoded = encodeURIComponent(text);
    if (mode === "analyze") {
      navigate(`/analyze/${ws.id}`);
    } else if (mode === "legal") {
      navigate(`/ask/${ws.id}?q=${encoded}&mode=legal`);
    } else {
      navigate(`/ask/${ws.id}?q=${encoded}&mode=document`);
    }
  }, [activeWorkspace, workspaces, setActiveWorkspace, navigate]);

  /** CommandBar Enter — use intent detection to route smartly */
  const handleCommandSubmit = useCallback(async (text: string, files?: File[]) => {
    if (files && files.length > 0) {
      handleNavigateWithMode(text, "document", files);
      return;
    }
    const ws = activeWorkspace ?? workspaces?.[0];
    if (!ws) { setShowCreateModal(true); return; }

    setIsProcessing(true);
    try {
      const result = await detectIntent.mutateAsync(text);
      const intent = result.intent;
      if (intent === "ANALYZE_RISK") {
        handleNavigateWithMode("", "analyze");
      } else if (intent === "ASK_LAW" || intent === "CHECK_VALIDITY") {
        handleNavigateWithMode(text, "legal");
      } else {
        handleNavigateWithMode(text, "document");
      }
    } catch {
      handleNavigateWithMode(text, "legal"); // fallback to legal on error
    } finally {
      setIsProcessing(false);
    }
  }, [activeWorkspace, workspaces, detectIntent, handleNavigateWithMode]);

  const handleFileDrop = useCallback((files: File[]) => {
    const ws = activeWorkspace ?? workspaces?.[0];
    if (!ws) {
      setShowCreateModal(true);
      return;
    }
    if (files.length > 0) {
      setPendingFiles(files);
    }
  }, [activeWorkspace, workspaces]);

  const handleFileIntentChoice = useCallback(async (choice: "analyze" | "ask" | "library") => {
    const ws = activeWorkspace ?? workspaces?.[0];
    if (!ws || !pendingFiles?.length) return;

    const file = pendingFiles[0];
    setPendingFiles(null);

    if (choice === "library") {
      navigate(`/library/${ws.id}`);
      return;
    }

    // Upload then navigate
    setUploadingFile(true);
    try {
      const doc = await uploadDocument.mutateAsync(file);
      toast.success("Đã tải lên thành công. Đang xử lý...");
      if (choice === "analyze") {
        navigate(`/analyze/${ws.id}?documentId=${doc.id}`);
      } else {
        navigate(`/ask/${ws.id}?q=${encodeURIComponent(`Tóm tắt nghĩa vụ trong ${doc.original_filename || file.name}`)}`);
      }
    } catch {
      toast.error("Không thể tải lên tài liệu. Vui lòng thử lại.");
    } finally {
      setUploadingFile(false);
    }
  }, [activeWorkspace, workspaces, pendingFiles, uploadDocument, navigate]);

  const hasWorkspaces = workspaces && workspaces.length > 0;

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Hero section */}
      <div className="flex flex-col items-center justify-center flex-1 px-4 py-12 min-h-[60vh]">
        {/* Logo + heading */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary mb-4">
            <Scale className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-primary mb-2">LexGuardian</h1>
          <p className="text-base text-gray-500">Trợ lý pháp lý AI của bạn</p>
        </div>

        {/* Command bar */}
        <div className="w-full max-w-2xl">
          <CommandBar
            value={commandText}
            onChange={setCommandText}
            onSubmit={handleCommandSubmit}
            onFilesDrop={handleFileDrop}
            isLoading={isProcessing}
            placeholder="Nhập câu hỏi hoặc chọn chế độ bên dưới..."
          />
        </div>

        {/* 3 Mode Cards */}
        <div className="w-full max-w-2xl mt-3 grid grid-cols-3 gap-3">
          {/* Legal consultation */}
          <button
            onClick={() => handleNavigateWithMode(commandText || "Tư vấn pháp luật", "legal")}
            className="group flex flex-col items-start gap-2 p-4 rounded-xl border border-gray-100 bg-white hover:border-blue-200 hover:bg-blue-50/50 hover:shadow-sm transition-all text-left"
          >
            <div className="w-8 h-8 rounded-lg bg-blue-100 group-hover:bg-blue-200 flex items-center justify-center transition-colors">
              <Globe className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800">Tư vấn pháp luật</p>
              <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
                Tra cứu quy định từ nguồn pháp lý uy tín
              </p>
            </div>
          </button>

          {/* Document QA */}
          <button
            onClick={() => handleNavigateWithMode(commandText || "Hỏi đáp tài liệu", "document")}
            className="group flex flex-col items-start gap-2 p-4 rounded-xl border border-gray-100 bg-white hover:border-emerald-200 hover:bg-emerald-50/50 hover:shadow-sm transition-all text-left"
          >
            <div className="w-8 h-8 rounded-lg bg-emerald-100 group-hover:bg-emerald-200 flex items-center justify-center transition-colors">
              <FileText className="w-4 h-4 text-emerald-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800">Hỏi đáp tài liệu</p>
              <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
                Đặt câu hỏi về hợp đồng đã tải lên
              </p>
            </div>
          </button>

          {/* Risk analysis */}
          <button
            onClick={() => handleNavigateWithMode("", "analyze")}
            className="group flex flex-col items-start gap-2 p-4 rounded-xl border border-gray-100 bg-white hover:border-orange-200 hover:bg-orange-50/50 hover:shadow-sm transition-all text-left"
          >
            <div className="w-8 h-8 rounded-lg bg-orange-100 group-hover:bg-orange-200 flex items-center justify-center transition-colors">
              <Shield className="w-4 h-4 text-orange-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800">Phân tích rủi ro</p>
              <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
                Phát hiện điều khoản bất lợi trong hợp đồng
              </p>
            </div>
          </button>
        </div>

        {/* Workspace prompt */}
        {!hasWorkspaces && !workspacesLoading && (
          <p className="mt-4 text-sm text-gray-400">
            Tạo một{" "}
            <button
              onClick={() => setShowCreateModal(true)}
              className="text-primary hover:underline font-medium"
            >
              Brief mới
            </button>{" "}
            để bắt đầu tải tài liệu lên
          </p>
        )}
      </div>

      {/* Recent Briefs */}
      {hasWorkspaces && (
        <div className="px-4 pb-10 max-w-4xl mx-auto w-full">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
              Recent Briefs
            </h2>
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-1 text-xs text-primary hover:underline font-medium"
            >
              <Plus className="w-3 h-3" />
              New Brief
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                onClick={() => handleBriefClick(ws)}
                className={cn(
                  "group text-left p-4 rounded-xl border bg-white hover:shadow-ambient transition-all",
                  activeWorkspace?.id === ws.id
                    ? "border-primary/30 bg-primary/5 ring-1 ring-primary/20"
                    : "border-gray-100 hover:border-gray-200"
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cn(
                    "w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0",
                    activeWorkspace?.id === ws.id ? "bg-primary/15" : "bg-gray-100 group-hover:bg-primary/10"
                  )}>
                    <FileText className={cn(
                      "w-4 h-4 transition-colors",
                      activeWorkspace?.id === ws.id ? "text-primary" : "text-gray-400 group-hover:text-primary"
                    )} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{ws.name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {ws.document_count} tài liệu • {formatDate(ws.created_at)}
                    </p>
                    {ws.indexed_count > 0 && ws.indexed_count < ws.document_count && (
                      <div className="mt-1.5 h-1 rounded-full bg-gray-100 overflow-hidden w-16">
                        <div
                          className="h-full bg-primary/40 rounded-full transition-all"
                          style={{ width: `${(ws.indexed_count / ws.document_count) * 100}%` }}
                        />
                      </div>
                    )}
                  </div>
                </div>
              </button>
            ))}

            {/* Create new brief card */}
            <button
              onClick={() => setShowCreateModal(true)}
              className="p-4 rounded-xl border border-dashed border-gray-200 bg-transparent hover:border-primary/30 hover:bg-primary/5 transition-all group text-left"
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gray-100 group-hover:bg-primary/10 flex items-center justify-center transition-colors">
                  <Plus className="w-4 h-4 text-gray-400 group-hover:text-primary transition-colors" />
                </div>
                <span className="text-sm text-gray-400 group-hover:text-primary font-medium transition-colors">
                  New Brief
                </span>
              </div>
            </button>
          </div>
        </div>
      )}

      {/* Empty state for no workspaces */}
      {!hasWorkspaces && !workspacesLoading && (
        <div className="pb-12">
          <EmptyState
            icon={<FileText className="w-10 h-10" />}
            title="Chưa có Brief nào"
            description="Tạo Brief đầu tiên để tải tài liệu lên và bắt đầu phân tích pháp lý"
            action={{ label: "Tạo Brief đầu tiên", onClick: () => setShowCreateModal(true) }}
          />
        </div>
      )}

      {/* Loading state */}
      {workspacesLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 animate-spin text-gray-300" />
        </div>
      )}

      {/* File intent modal */}
      {pendingFiles && pendingFiles.length > 0 && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-base font-semibold text-gray-900">
                Bạn muốn làm gì với hợp đồng này?
              </h2>
              <button
                onClick={() => setPendingFiles(null)}
                className="p-1 rounded-md text-gray-400 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-gray-400 mb-5 truncate">
              {pendingFiles[0].name}
            </p>

            {uploadingFile ? (
              <div className="flex items-center justify-center py-6 gap-2 text-sm text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin text-primary" />
                Đang tải lên...
              </div>
            ) : (
              <div className="space-y-2">
                <button
                  onClick={() => handleFileIntentChoice("analyze")}
                  className="w-full flex items-start gap-3 px-4 py-3.5 rounded-xl border border-gray-100 hover:border-primary/30 hover:bg-primary/5 transition-all group text-left"
                >
                  <Shield className="w-5 h-5 text-primary mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">Phân tích Rủi ro</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Phát hiện điều khoản bất lợi và rủi ro pháp lý
                    </p>
                  </div>
                </button>
                <button
                  onClick={() => handleFileIntentChoice("ask")}
                  className="w-full flex items-start gap-3 px-4 py-3.5 rounded-xl border border-gray-100 hover:border-primary/30 hover:bg-primary/5 transition-all group text-left"
                >
                  <BookOpen className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">Tóm tắt Nghĩa vụ</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Trích xuất nghĩa vụ các bên từ hợp đồng
                    </p>
                  </div>
                </button>
                <button
                  onClick={() => handleFileIntentChoice("library")}
                  className="w-full flex items-start gap-3 px-4 py-3.5 rounded-xl border border-gray-100 hover:border-primary/30 hover:bg-primary/5 transition-all group text-left"
                >
                  <Library className="w-5 h-5 text-gray-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">Thêm vào Thư viện</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Lưu tài liệu để tra cứu và hỏi đáp sau
                    </p>
                  </div>
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Create Brief modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold text-gray-900">New Brief</h2>
              <button
                onClick={() => { setShowCreateModal(false); setNewBriefName(""); }}
                className="p-1 rounded-md text-gray-400 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Tên Brief
                </label>
                <input
                  type="text"
                  value={newBriefName}
                  onChange={(e) => setNewBriefName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateBrief()}
                  placeholder="e.g., Hợp đồng NDA Q4 2024"
                  autoFocus
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => { setShowCreateModal(false); setNewBriefName(""); }}
                  className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100 transition-colors"
                >
                  Hủy
                </button>
                <button
                  onClick={handleCreateBrief}
                  disabled={!newBriefName.trim() || creatingWorkspace}
                  className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {creatingWorkspace && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Tạo Brief
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
