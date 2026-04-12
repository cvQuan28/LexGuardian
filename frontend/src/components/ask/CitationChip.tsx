import { cn } from "@/lib/utils";
import type { ChatSourceChunk } from "@/types";

interface CitationChipProps {
  citation: ChatSourceChunk;
  onClick: (citation: ChatSourceChunk) => void;
  className?: string;
}

export function CitationChip({ citation, onClick, className }: CitationChipProps) {
  const label = citation.source_label
    ? `${citation.source_label}${citation.page_no ? `, p.${citation.page_no}` : ""}`
    : `Doc ${citation.document_id}${citation.page_no ? `, p.${citation.page_no}` : ""}`;

  return (
    <button
      role="button"
      aria-label={`View source: ${label}`}
      onClick={() => onClick(citation)}
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono",
        "bg-primary/8 text-primary/70 hover:bg-primary/15 hover:text-primary",
        "border border-primary/15 hover:border-primary/30",
        "transition-colors cursor-pointer underline-offset-2 hover:underline",
        className,
      )}
    >
      [{label}]
    </button>
  );
}
