import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Square, Brain, Scale, Globe, FileText, User, Trash2, MessageSquare, Plus, ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { StreamingAnswer } from "@/components/ask/StreamingAnswer";
import { SourceViewer } from "@/components/ask/SourceViewer";
import { WebSourcePanel } from "@/components/ask/WebSourcePanel";
import { useLegalStream } from "@/hooks/useLegalStream";
import { useDocuments } from "@/hooks/useDocuments";
import { useWorkspace } from "@/hooks/useWorkspaces";
import { useChatHistory, useClearChatHistory } from "@/hooks/useChatHistory";
import { useConversations, useDeleteConversation } from "@/hooks/useConversations";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { ChatMessage, ChatSourceChunk } from "@/types";

// Map URL ?mode param → ChatAssistantMode sent to the backend
function resolveAssistantMode(mode: string | null): "document_qa" | "legal_consultation" {
  return mode === "legal" ? "legal_consultation" : "document_qa";
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "Hôm nay";
  if (diffDays === 1) return "Hôm qua";
  if (diffDays < 7) return `${diffDays} ngày trước`;
  return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
}

export function AskPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const urlMode = searchParams.get("mode");
  const assistantMode = resolveAssistantMode(urlMode);
  const queryClient = useQueryClient();

  const toggleMode = useCallback(() => {
    const next = assistantMode === "legal_consultation" ? "document" : "legal";
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set("mode", next);
      p.delete("q");
      return p;
    });
  }, [assistantMode, setSearchParams]);

  const wsId = workspaceId ?? "";
  const { data: workspace } = useWorkspace(wsId ? Number(wsId) : null);
  const { data: documents = [] } = useDocuments(wsId ? Number(wsId) : null);

  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const sourceViewer = useWorkspaceStore((s) => s.sourceViewer);
  const openCitation = useWorkspaceStore((s) => s.openCitation);
  const closeSourceViewer = useWorkspaceStore((s) => s.closeSourceViewer);
  const webSource = useWorkspaceStore((s) => s.webSource);
  const closeWebSource = useWorkspaceStore((s) => s.closeWebSource);

  const stream = useLegalStream(wsId);

  // Conversation state
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [showConvPanel, setShowConvPanel] = useState(false);

  const { data: conversations } = useConversations(wsId);
  const deleteConversation = useDeleteConversation(wsId);

  // Load chat history only when a conversation is selected
  const { data: chatHistory } = useChatHistory(
    activeConversationId != null ? wsId : "",
    activeConversationId
  );
  const clearHistory = useClearChatHistory(wsId, activeConversationId ?? undefined);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [inputText, setInputText] = useState("");
  const [enableThinking, setEnableThinking] = useState(false);
  const autoSubmittedRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastSentTextRef = useRef<string>("");

  // Set active workspace when data loads
  useEffect(() => {
    if (workspace) setActiveWorkspace(workspace);
  }, [workspace, setActiveWorkspace]);

  // Load persisted history when conversation is selected
  useEffect(() => {
    if (historyLoaded || !chatHistory?.messages?.length) return;
    setHistoryLoaded(true);
    setMessages(
      chatHistory.messages.map((m) => ({
        id: m.message_id,
        role: m.role,
        content: m.content,
        timestamp: m.created_at,
        sources: m.sources ?? undefined,
        agentSteps: m.agent_steps ?? undefined,
      }))
    );
  }, [chatHistory, historyLoaded]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stream.streamingContent]);

  // Auto-submit initial query from URL
  useEffect(() => {
    if (initialQuery && !autoSubmittedRef.current && wsId) {
      autoSubmittedRef.current = true;
      handleSend(initialQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, initialQuery]);

  const handleCancel = useCallback(() => {
    stream.cancel();
    setInputText(lastSentTextRef.current);
  }, [stream]);

  const handleSend = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || stream.isStreaming) return;

    lastSentTextRef.current = trimmed;
    setInputText("");

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    const history = messages.slice(-10).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const result = await stream.sendMessage(
      trimmed,
      history,
      enableThinking,
      activeConversationId,
      false,
      assistantMode,
    );

    if (result) {
      setMessages((prev) => [...prev, result]);
      const resolvedConvId = result.conversationId ?? activeConversationId;
      // Always invalidate chat history so switching away and back shows fresh data
      queryClient.invalidateQueries({ queryKey: ["chat-history", wsId, resolvedConvId ?? "none"] });
      queryClient.invalidateQueries({ queryKey: ["conversations", wsId] });
      if (result.conversationId && !activeConversationId) {
        setActiveConversationId(result.conversationId);
      }
    }
    stream.reset();
  }, [stream, messages, enableThinking, assistantMode, activeConversationId, wsId, queryClient]);

  const handleCitationClick = useCallback(
    (citation: ChatSourceChunk) => {
      openCitation(citation, documents);
    },
    [openCitation, documents]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(inputText);
    }
  };

  function switchConversation(convId: number) {
    if (activeConversationId === convId) return;
    setActiveConversationId(convId);
    setMessages([]);
    setHistoryLoaded(false);
    stream.reset();
  }

  function startNewChat() {
    setActiveConversationId(null);
    setMessages([]);
    setHistoryLoaded(false);
    setInputText("");
    stream.reset();
  }

  const isRightPanelOpen = (sourceViewer.open && sourceViewer.document != null) || webSource.open;
  const contextNearLimit = messages.length >= 10;
  const contextAtLimit = messages.length >= 20;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Conversation sidebar */}
      {showConvPanel && (
        <div className="w-52 border-r border-gray-100 flex-shrink-0 flex flex-col h-full bg-white">
          {/* Sidebar header */}
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-100">
            <span className="text-xs font-semibold text-gray-600">Lịch sử hội thoại</span>
            <button
              onClick={() => setShowConvPanel(false)}
              className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* New chat button */}
          <div className="px-2 py-2 border-b border-gray-50">
            <button
              onClick={startNewChat}
              className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-medium text-primary border border-primary/20 hover:bg-primary/5 transition-colors"
            >
              <Plus className="w-3 h-3" />
              Hội thoại mới
            </button>
          </div>

          {/* Conversations list */}
          <div className="flex-1 overflow-y-auto custom-scrollbar py-1">
            {!conversations?.length && (
              <p className="text-[10px] text-gray-400 text-center mt-4 px-3">
                Chưa có hội thoại nào
              </p>
            )}
            {conversations?.map((conv) => (
              <div
                key={conv.id}
                className={cn(
                  "group relative flex items-start gap-1.5 px-2 py-2 mx-1 rounded-lg cursor-pointer transition-colors",
                  activeConversationId === conv.id
                    ? "bg-primary/10 text-primary"
                    : "hover:bg-gray-50 text-gray-600"
                )}
                onClick={() => switchConversation(conv.id)}
              >
                <MessageSquare className={cn(
                  "w-3 h-3 flex-shrink-0 mt-0.5",
                  activeConversationId === conv.id ? "text-primary" : "text-gray-400"
                )} />
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-medium leading-snug truncate">
                    {conv.title || "Hội thoại"}
                  </p>
                  <p className="text-[9px] text-gray-400 mt-0.5">
                    {formatRelativeTime(conv.updated_at)}
                  </p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteConversation.mutate(conv.id, {
                      onSuccess: () => {
                        if (activeConversationId === conv.id) startNewChat();
                      },
                    });
                  }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-gray-400 hover:text-red-400 transition-all flex-shrink-0"
                  title="Xóa"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chat panel */}
      <div className="flex flex-col h-full flex-1 overflow-hidden min-w-0">
        {/* Messages list */}
        <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-6 space-y-6">
          {messages.length === 0 && !stream.isStreaming && (
            <div className="flex flex-col items-center justify-center h-full text-center py-20">
              <Scale className="w-10 h-10 text-gray-200 mb-3" />
              <p className="text-sm font-medium text-gray-500">
                {workspace?.name ?? "LexGuardian"}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                {assistantMode === "legal_consultation"
                  ? "Tra cứu pháp luật — tìm kiếm trên các nguồn pháp lý uy tín"
                  : "Hỏi đáp về tài liệu — câu trả lời dựa trên tài liệu trong Brief"}
              </p>
              <div className={cn(
                "mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border",
                assistantMode === "legal_consultation"
                  ? "bg-blue-50 text-blue-700 border-blue-200"
                  : "bg-gray-50 text-gray-600 border-gray-200"
              )}>
                {assistantMode === "legal_consultation"
                  ? <><Globe className="w-3.5 h-3.5" /> Tra cứu pháp luật trực tuyến</>
                  : <><FileText className="w-3.5 h-3.5" /> Hỏi đáp từ tài liệu</>
                }
              </div>
            </div>
          )}

          {/* Context overflow warning */}
          {contextAtLimit && (
            <div className="flex justify-center">
              <div className="px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-100 text-[10px] text-amber-600 text-center max-w-xs">
                Ngữ cảnh đã đạt giới hạn ({messages.length} tin nhắn). Chỉ 10 tin nhắn gần nhất được gửi đến AI. Hãy bắt đầu hội thoại mới để có kết quả tốt hơn.
              </div>
            </div>
          )}
          {!contextAtLimit && contextNearLimit && (
            <div className="flex justify-center">
              <div className="px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-100 text-[10px] text-gray-400 text-center max-w-xs">
                Ngữ cảnh gần đầy ({messages.length}/20). AI chỉ nhớ 10 tin nhắn gần nhất.
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex gap-3",
                msg.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {msg.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Brain className="w-3.5 h-3.5 text-white" />
                </div>
              )}

              <div
                className={cn(
                  "max-w-[85%] rounded-2xl px-4 py-3",
                  msg.role === "user"
                    ? "bg-primary text-white rounded-br-md"
                    : "bg-white border border-gray-100 shadow-sm rounded-bl-md"
                )}
              >
                {msg.role === "user" ? (
                  <p className="text-sm leading-relaxed">{msg.content}</p>
                ) : (
                  <StreamingAnswer
                    content={msg.content}
                    isStreaming={false}
                    agentSteps={msg.agentSteps ?? []}
                    sources={msg.sources ?? []}
                    onCitationClick={handleCitationClick}
                  />
                )}
              </div>

              {msg.role === "user" && (
                <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5 text-gray-500" />
                </div>
              )}
            </div>
          ))}

          {/* Streaming message */}
          {stream.isStreaming && (
            <div className="flex gap-3 justify-start">
              <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center flex-shrink-0 mt-0.5">
                <Brain className="w-3.5 h-3.5 text-white" />
              </div>
              <div className="max-w-[85%] bg-white border border-gray-100 shadow-sm rounded-2xl rounded-bl-md px-4 py-3">
                <StreamingAnswer
                  content={stream.streamingContent}
                  isStreaming={stream.isStreaming}
                  agentSteps={stream.agentSteps}
                  sources={stream.pendingSources}
                  onCitationClick={handleCitationClick}
                />
              </div>
            </div>
          )}

          {/* Error state */}
          {stream.error && (
            <div className="flex justify-center">
              <div className="px-4 py-2 rounded-lg bg-red-50 border border-red-100 text-xs text-red-600">
                {stream.error}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input bar */}
        <div className="border-t border-gray-100 bg-white px-4 py-3">
          <div className="flex items-end gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
            {/* Conversations toggle */}
            <button
              type="button"
              onClick={() => setShowConvPanel((v) => !v)}
              title="Lịch sử hội thoại"
              className={cn(
                "flex-shrink-0 p-1.5 rounded-md transition-colors",
                showConvPanel
                  ? "bg-primary/10 text-primary"
                  : "text-gray-300 hover:text-gray-500 hover:bg-gray-100"
              )}
            >
              <MessageSquare className="w-4 h-4" />
            </button>

            {/* Mode toggle */}
            <button
              type="button"
              onClick={toggleMode}
              title={assistantMode === "legal_consultation" ? "Chế độ: Tư vấn pháp luật — nhấn để đổi sang Hỏi đáp tài liệu" : "Chế độ: Hỏi đáp tài liệu — nhấn để đổi sang Tư vấn pháp luật"}
              className={cn(
                "flex-shrink-0 p-1.5 rounded-md transition-colors",
                assistantMode === "legal_consultation"
                  ? "bg-blue-50 text-blue-600 hover:bg-blue-100"
                  : "bg-emerald-50 text-emerald-600 hover:bg-emerald-100"
              )}
            >
              {assistantMode === "legal_consultation"
                ? <Globe className="w-4 h-4" />
                : <FileText className="w-4 h-4" />
              }
            </button>

            {/* Thinking toggle */}
            <button
              type="button"
              onClick={() => setEnableThinking((p) => !p)}
              title={enableThinking ? "Thinking on" : "Thinking off"}
              className={cn(
                "flex-shrink-0 p-1.5 rounded-md transition-colors",
                enableThinking
                  ? "bg-primary/10 text-primary"
                  : "text-gray-300 hover:text-gray-500 hover:bg-gray-100"
              )}
            >
              <Brain className="w-4 h-4" />
            </button>

            <textarea
              value={inputText}
              onChange={(e) => {
                setInputText(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
              }}
              onKeyDown={handleKeyDown}
              placeholder="Đặt câu hỏi (Enter để gửi, Shift+Enter để xuống dòng)..."
              rows={1}
              className="flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none min-h-[24px] leading-6 scrollbar-none"
              style={{ maxHeight: "120px" }}
            />

            {stream.isStreaming ? (
              <button
                type="button"
                onClick={handleCancel}
                title="Hủy"
                className="flex-shrink-0 p-1.5 rounded-lg transition-all bg-red-50 text-red-400 hover:bg-red-100 hover:text-red-600"
              >
                <Square className="w-4 h-4 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => handleSend(inputText)}
                disabled={!inputText.trim()}
                className={cn(
                  "flex-shrink-0 p-1.5 rounded-lg transition-all",
                  inputText.trim()
                    ? "bg-primary text-white hover:bg-primary/90"
                    : "bg-gray-100 text-gray-300 cursor-not-allowed"
                )}
              >
                <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>

          <div className="flex items-center justify-between mt-1.5 px-1">
            <p className="text-[10px] text-gray-300">
              {workspace?.name} • {documents.length} tài liệu
            </p>
            <div className="flex items-center gap-2">
              {enableThinking && (
                <p className="text-[10px] text-primary/60 font-medium">
                  Thinking enabled
                </p>
              )}
              {messages.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    clearHistory.mutate();
                    setMessages([]);
                    setHistoryLoaded(false);
                  }}
                  title="Xóa lịch sử chat"
                  className="flex items-center gap-1 text-[10px] text-gray-300 hover:text-red-400 transition-colors"
                >
                  <Trash2 className="w-3 h-3" />
                  Xóa lịch sử
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Right panel: Source Viewer or Web Source Panel */}
      <div
        className={cn(
          "flex-shrink-0 transition-all duration-300 overflow-hidden",
          isRightPanelOpen ? "w-[45%]" : "w-0"
        )}
      >
        {sourceViewer.open && sourceViewer.document && (
          <SourceViewer
            doc={sourceViewer.document}
            scrollToPage={sourceViewer.scrollToPage}
            scrollToHeading={sourceViewer.scrollToHeading ?? undefined}
            highlightText={sourceViewer.highlightText ?? undefined}
            onClose={closeSourceViewer}
          />
        )}
        {webSource.open && (
          <WebSourcePanel
            title={webSource.title}
            url={webSource.url}
            content={webSource.content}
            source_label={webSource.source_label}
            onClose={closeWebSource}
          />
        )}
      </div>
    </div>
  );
}
