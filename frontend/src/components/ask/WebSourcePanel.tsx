import { X, ExternalLink, Globe } from "lucide-react";

interface WebSourcePanelProps {
  title: string;
  url: string;
  content: string;
  source_label?: string;
  onClose: () => void;
}

export function WebSourcePanel({ title, url, content, source_label, onClose }: WebSourcePanelProps) {
  const displayTitle = title || source_label || "Nguồn web";

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-start justify-between px-4 py-3 border-b border-gray-100 gap-2">
        <div className="flex items-start gap-2 min-w-0 flex-1">
          <Globe className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-gray-800 leading-snug break-words">
              {displayTitle}
            </p>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-blue-500 hover:underline break-all block mt-0.5 leading-tight"
              >
                {url}
              </a>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1.5 rounded-md text-gray-400 hover:bg-gray-100 hover:text-blue-500 transition-colors"
              title="Mở liên kết"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
            title="Đóng"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
        <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
          {content}
        </p>
      </div>
    </div>
  );
}
