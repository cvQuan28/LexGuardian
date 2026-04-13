import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ArrowRight, Loader2, Brain, Scale, Globe, FileText, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { StreamingAnswer } from "@/components/ask/StreamingAnswer";
import { SourceViewer } from "@/components/ask/SourceViewer";
import { useLegalStream } from "@/hooks/useLegalStream";
import { useDocuments } from "@/hooks/useDocuments";
import { useWorkspace } from "@/hooks/useWorkspaces";
import { useChatHistory } from "@/hooks/useChatHistory";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { ChatMessage, ChatSourceChunk } from "@/types";

// Map URL ?mode param → ChatAssistantMode sent to the backend
function resolveAssistantMode(mode: string | null): "document_qa" | "legal_consultation" {
  return mode === "legal" ? "legal_consultation" : "document_qa";
}

export function AskPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const urlMode = searchParams.get("mode");
  const assistantMode = resolveAssistantMode(urlMode);

  const toggleMode = useCallback(() => {
    const next = assistantMode === "legal_consultation" ? "document" : "legal";
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set("mode", next);
      p.delete("q"); // clear auto-submit so it doesn't re-fire
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

  const stream = useLegalStream(wsId);
  const { data: chatHistory } = useChatHistory(wsId);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [inputText, setInputText] = useState("");
  const [enableThinking, setEnableThinking] = useState(false);
  const autoSubmittedRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Set active workspace when data loads
  useEffect(() => {
    if (workspace) setActiveWorkspace(workspace);
  }, [workspace, setActiveWorkspace]);

  // Load persisted history on first mount (only once per workspace)
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

  const handleSend = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || stream.isStreaming) return;

    setInputText("");

    // Add user message
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // Build history for context
    const history = messages.slice(-10).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Stream response — pass assistant_mode derived from URL intent
    const result = await stream.sendMessage(
      trimmed,
      history,
      enableThinking,
      null,       // conversationId
      false,      // forceSearch
      assistantMode,
    );

    if (result) {
      setMessages((prev) => [...prev, result]);
      stream.reset();
    }
  }, [stream, messages, enableThinking, assistantMode]);

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

  const isViewerOpen = sourceViewer.open && sourceViewer.document != null;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Chat panel */}
      <div
        className={cn(
          "flex flex-col h-full transition-all duration-300",
          isViewerOpen ? "w-[55%] border-r border-gray-100" : "w-full"
        )}
      >
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
              {/* Mode badge */}
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
                // Auto-grow
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
              }}
              onKeyDown={handleKeyDown}
              placeholder="Đặt câu hỏi (Enter để gửi, Shift+Enter để xuống dòng)..."
              rows={1}
              disabled={stream.isStreaming}
              className="flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none min-h-[24px] leading-6 scrollbar-none"
              style={{ maxHeight: "120px" }}
            />

            <button
              type="button"
              onClick={() => handleSend(inputText)}
              disabled={!inputText.trim() || stream.isStreaming}
              className={cn(
                "flex-shrink-0 p-1.5 rounded-lg transition-all",
                inputText.trim() && !stream.isStreaming
                  ? "bg-primary text-white hover:bg-primary/90"
                  : "bg-gray-100 text-gray-300 cursor-not-allowed"
              )}
            >
              {stream.isStreaming ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ArrowRight className="w-4 h-4" />
              )}
            </button>
          </div>

          <div className="flex items-center justify-between mt-1.5 px-1">
            <p className="text-[10px] text-gray-300">
              {workspace?.name} • {documents.length} tài liệu
            </p>
            {enableThinking && (
              <p className="text-[10px] text-primary/60 font-medium">
                Thinking enabled
              </p>
            )}
          </div>
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
