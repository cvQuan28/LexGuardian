import { MemoizedMarkdown } from "./MemoizedMarkdown";
import { CitationChip } from "./CitationChip";
import { ThinkingTimeline } from "./ThinkingTimeline";
import { cn } from "@/lib/utils";
import type { ChatSourceChunk, AgentStep } from "@/types";

interface StreamingAnswerProps {
  content: string;
  isStreaming: boolean;
  agentSteps: AgentStep[];
  sources: ChatSourceChunk[];
  onCitationClick: (citation: ChatSourceChunk) => void;
  className?: string;
}

export function StreamingAnswer({
  content,
  isStreaming,
  agentSteps,
  sources,
  onCitationClick,
  className,
}: StreamingAnswerProps) {
  const hasContent = content.trim().length > 0;
  const showTimeline = agentSteps.length > 0;
  const autoCollapse = hasContent && isStreaming;

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {showTimeline && (
        <ThinkingTimeline
          steps={agentSteps}
          mode={isStreaming ? "live" : "embedded"}
          autoCollapse={autoCollapse}
        />
      )}
      {hasContent && (
        <div className="font-serif text-base leading-7 text-gray-900 prose prose-neutral max-w-none">
          <MemoizedMarkdown content={content} id="streaming-answer" isStreaming={isStreaming} />
        </div>
      )}
      {sources.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1 border-t border-gray-100">
          <span className="text-xs text-gray-400 self-center">Sources:</span>
          {sources.map((src, i) => (
            <CitationChip
              key={`${src.document_id}-${src.page_no}-${i}`}
              citation={src}
              onClick={onCitationClick}
            />
          ))}
        </div>
      )}
      {isStreaming && !hasContent && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span className="inline-flex gap-1">
            <span className="animate-bounce" style={{ animationDelay: "0ms" }}>·</span>
            <span className="animate-bounce" style={{ animationDelay: "75ms" }}>·</span>
            <span className="animate-bounce" style={{ animationDelay: "150ms" }}>·</span>
          </span>
        </div>
      )}
    </div>
  );
}
