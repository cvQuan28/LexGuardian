import { useState, useRef, useCallback, useEffect } from "react";
import { ArrowRight, Loader2, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";

interface CommandBarProps {
  onSubmit: (text: string, files?: File[]) => void;
  onFilesDrop?: (files: File[]) => void;
  suggestions?: string[];
  isLoading?: boolean;
  placeholder?: string;
  disabled?: boolean;
  // controlled mode
  value?: string;
  onChange?: (v: string) => void;
}

export function CommandBar({
  onSubmit,
  onFilesDrop,
  suggestions = [],
  isLoading = false,
  placeholder = "Nhập câu hỏi pháp lý của bạn...",
  disabled = false,
  value: controlledValue,
  onChange: onControlledChange,
}: CommandBarProps) {
  const isControlled = controlledValue !== undefined;
  const [internalText, setInternalText] = useState("");
  const text = isControlled ? controlledValue! : internalText;
  const setText = (v: string) => {
    if (isControlled) onControlledChange?.(v);
    else setInternalText(v);
  };
  const [isDragOver, setIsDragOver] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-grow textarea (1–4 lines)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = 24;
    const minH = lineHeight;
    const maxH = lineHeight * 4;
    el.style.height = `${Math.min(Math.max(el.scrollHeight, minH), maxH)}px`;
  }, [text]);

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isLoading || disabled) return;
    onSubmit(trimmed, pendingFiles.length > 0 ? pendingFiles : undefined);
    setText("");
    setPendingFiles([]);
  }, [text, isLoading, disabled, onSubmit, pendingFiles]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const files = Array.from(e.dataTransfer.files).filter(
        (f) => f.type === "application/pdf"
      );
      if (files.length > 0) {
        setPendingFiles((prev) => [...prev, ...files]);
        onFilesDrop?.(files);
      }
    },
    [onFilesDrop]
  );

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length > 0) {
        setPendingFiles((prev) => [...prev, ...files]);
        onFilesDrop?.(files);
      }
    },
    [onFilesDrop]
  );

  const canSubmit = text.trim().length > 0 && !isLoading && !disabled;

  return (
    <div className="w-full flex flex-col gap-3">
      {/* Main input bar */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "relative flex items-end gap-2 rounded-2xl border bg-white shadow-ambient px-4 py-3 transition-all",
          isDragOver
            ? "border-primary/50 bg-primary/5 ring-2 ring-primary/20"
            : "border-gray-200 hover:border-gray-300 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10",
          disabled && "opacity-60 pointer-events-none"
        )}
      >
        {/* Attachment button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="flex-shrink-0 p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          aria-label="Attach file"
        >
          <Paperclip className="w-4 h-4" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          className="hidden"
          onChange={handleFileInputChange}
        />

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isDragOver ? "Thả tệp PDF vào đây..." : placeholder}
          rows={1}
          disabled={disabled || isLoading}
          className={cn(
            "flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400",
            "focus:outline-none min-h-[24px] leading-6",
            "scrollbar-none"
          )}
          style={{ maxHeight: "96px" }}
        />

        {/* Send / loading button */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className={cn(
            "flex-shrink-0 p-2 rounded-xl transition-all",
            canSubmit
              ? "bg-primary text-white hover:bg-primary/90 shadow-sm"
              : "bg-gray-100 text-gray-300 cursor-not-allowed"
          )}
          aria-label="Send"
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ArrowRight className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Pending files */}
      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {pendingFiles.map((f, i) => (
            <div
              key={`${f.name}-${i}`}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium"
            >
              <Paperclip className="w-3 h-3" />
              <span className="max-w-[150px] truncate">{f.name}</span>
              <button
                onClick={() => setPendingFiles((prev) => prev.filter((_, j) => j !== i))}
                className="ml-0.5 text-primary/60 hover:text-primary"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Suggestion chips */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setText(s)}
              disabled={disabled || isLoading}
              className="px-3 py-1.5 rounded-full text-xs font-medium text-gray-600 bg-surface-low border border-gray-200 hover:bg-surface-mid hover:border-gray-300 transition-colors disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
