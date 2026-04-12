import { useState, useEffect, useRef, useMemo, useCallback, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { FileText, List, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { Document } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Heading {
  id: string;
  text: string;
  level: number;
}

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------
function ViewerSkeleton() {
  return (
    <div className="p-6 space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-3/5" />
      <div className="h-4 bg-gray-200 rounded w-full" />
      <div className="h-4 bg-gray-200 rounded w-4/5" />
      <div className="h-4 bg-gray-200 rounded w-full" />
      <div className="h-4 bg-gray-200 rounded w-2/3" />
      <div className="h-20 bg-gray-200 rounded w-full mt-4" />
      <div className="h-4 bg-gray-200 rounded w-full" />
      <div className="h-4 bg-gray-200 rounded w-3/4" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------
function ViewerError({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <FileText className="w-10 h-10 text-gray-300 mb-3" />
      <p className="text-sm font-medium text-gray-700">Unable to load document</p>
      <p className="text-xs text-gray-400 mt-1 max-w-xs">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------
function ViewerEmpty() {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <FileText className="w-10 h-10 text-gray-300 mb-3" />
      <p className="text-sm text-gray-500">
        No parsed content available for this document
      </p>
      <p className="text-xs text-gray-400 mt-1">
        The document may not have been processed yet
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table of Contents sidebar
// ---------------------------------------------------------------------------
const TOCSidebar = memo(function TOCSidebar({
  headings,
  activeId,
  onSelect,
}: {
  headings: Heading[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  if (headings.length === 0) return null;

  return (
    <nav className="w-48 flex-shrink-0 border-r border-gray-100 overflow-y-auto py-3 px-2 hidden xl:block">
      <div className="flex items-center gap-1.5 px-2 mb-2">
        <List className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Contents</span>
      </div>
      <ul className="space-y-0.5">
        {headings.map((h) => (
          <li key={h.id}>
            <button
              onClick={() => onSelect(h.id)}
              className={cn(
                "w-full text-left text-xs py-1 px-2 rounded-md transition-colors truncate",
                "hover:bg-gray-100",
                activeId === h.id
                  ? "text-primary font-medium bg-primary/10"
                  : "text-gray-500"
              )}
              style={{ paddingLeft: `${(h.level - 1) * 12 + 8}px` }}
              title={h.text}
            >
              {h.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
});

// ---------------------------------------------------------------------------
// Page divider
// ---------------------------------------------------------------------------
function PageDivider({ pageNo }: { pageNo: number }) {
  return (
    <div className="flex items-center gap-3 py-4 select-none" data-page={pageNo}>
      <div className="flex-1 border-t border-dashed border-gray-200" />
      <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">
        Page {pageNo}
      </span>
      <div className="flex-1 border-t border-dashed border-gray-200" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Extract headings from markdown for TOC
// ---------------------------------------------------------------------------
function extractHeadings(markdown: string): Heading[] {
  const headings: Heading[] = [];
  const lines = markdown.split("\n");
  for (const line of lines) {
    const match = line.match(/^(#{1,4})\s+(.+)/);
    if (match) {
      const level = match[1].length;
      const text = match[2].replace(/[*_`#]/g, "").trim();
      const id = text
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-")
        .slice(0, 80);
      headings.push({ id, text, level });
    }
  }
  return headings;
}

// ---------------------------------------------------------------------------
// Insert page dividers into markdown text
// ---------------------------------------------------------------------------
function insertPageDividers(markdown: string): string {
  return markdown.replace(
    /(?:<!--\s*page\s+(\d+)\s*-->|(?:^|\n)---+\s*\n+(?=##?\s))/gi,
    (match, pageNo) => {
      if (pageNo) return `\n\n<page-break data-page="${pageNo}" />\n\n`;
      return match;
    }
  );
}

function getHeadingText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(getHeadingText).join("");
  if (children && typeof children === "object" && "props" in children) {
    return getHeadingText((children as React.ReactElement<{ children?: React.ReactNode }>).props.children);
  }
  return String(children ?? "");
}

function generateHeadingId(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .slice(0, 80);
}

// ---------------------------------------------------------------------------
// SourceViewer
// ---------------------------------------------------------------------------
interface SourceViewerProps {
  doc: Document;
  scrollToPage?: number | null;
  scrollToHeading?: string | null;
  highlightText?: string | null;
  onClose?: () => void;
}

export const SourceViewer = memo(function SourceViewer({
  doc,
  scrollToPage,
  scrollToHeading,
  onClose,
}: SourceViewerProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const pageCounterRef = useRef(1);
  const [activeHeading, setActiveHeading] = useState<string | null>(null);
  const [showToc, setShowToc] = useState(true);

  // ---- Fetch markdown content ----
  const { data: markdown, isLoading, error } = useQuery({
    queryKey: ["document-markdown", doc.id],
    queryFn: () => api.getText(`/documents/${doc.id}/markdown`),
    enabled: doc.status === "indexed",
    staleTime: 5 * 60 * 1000,
  });

  // ---- Extract headings for TOC ----
  const headings = useMemo(
    () => (markdown ? extractHeadings(markdown) : []),
    [markdown]
  );

  // ---- Process markdown (insert page dividers) ----
  const processedMarkdown = useMemo(() => {
    pageCounterRef.current = 1;
    return markdown ? insertPageDividers(markdown) : "";
  }, [markdown]);

  // ---- Stable ReactMarkdown components ----
  const mdComponents = useMemo<import("react-markdown").Components>(() => ({
    h1: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h1 id={id} {...props}>{children}</h1>;
    },
    h2: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h2 id={id} {...props}>{children}</h2>;
    },
    h3: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h3 id={id} {...props}>{children}</h3>;
    },
    h4: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h4 id={id} {...props}>{children}</h4>;
    },
    hr: () => {
      pageCounterRef.current += 1;
      return <PageDivider pageNo={pageCounterRef.current} />;
    },
    img: ({ src, alt, ...props }) => (
      <figure className="my-4">
        <img
          src={src}
          alt={alt || ""}
          loading="lazy"
          className="rounded-lg max-w-full mx-auto border border-gray-100"
          style={{ minHeight: 80, objectFit: "contain" }}
          onLoad={(e) => {
            (e.target as HTMLImageElement).style.minHeight = "auto";
          }}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
          {...props}
        />
        {alt && (
          <figcaption className="text-xs text-gray-400 text-center mt-1.5 italic">
            {alt}
          </figcaption>
        )}
      </figure>
    ),
  }), []);

  // Stable plugin arrays
  const remarkPlugins = useMemo(() => [remarkGfm, remarkMath], []);
  const rehypePlugins = useMemo(() => [rehypeKatex], []);

  // ---- Intersection observer for active heading ----
  useEffect(() => {
    if (!contentRef.current || headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeading(entry.target.id);
          }
        }
      },
      { root: contentRef.current, rootMargin: "-20% 0px -60% 0px", threshold: 0 }
    );

    const headingElements = contentRef.current.querySelectorAll("h1, h2, h3, h4");
    headingElements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [headings, processedMarkdown]);

  // ---- Scroll animation helper ----
  const scrollTo = useCallback(
    (target: HTMLElement, block: "start" | "center" = "center") => {
      const container = contentRef.current;
      if (!container) return;

      const calcTarget = () => {
        let offset = 0;
        let el: HTMLElement | null = target;
        while (el && el !== container) {
          offset += el.offsetTop;
          el = el.offsetParent as HTMLElement | null;
        }
        const targetH = target.offsetHeight;
        const containerH = container.clientHeight;
        const dest =
          block === "center"
            ? offset - containerH / 2 + targetH / 2
            : offset;
        return Math.max(0, Math.min(dest, container.scrollHeight - containerH));
      };

      const animate = (dest: number) => {
        const start = container.scrollTop;
        const dist = dest - start;
        if (Math.abs(dist) < 1) return;
        const duration = Math.min(400, Math.abs(dist) * 0.5 + 150);
        const t0 = performance.now();
        const step = () => {
          const p = Math.min((performance.now() - t0) / duration, 1);
          const ease = 1 - Math.pow(1 - p, 3);
          container.scrollTop = start + dist * ease;
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      };

      animate(calcTarget());
      setTimeout(() => animate(calcTarget()), 800);
    },
    []
  );

  // ---- Scroll to page/heading when props change ----
  useEffect(() => {
    if (!contentRef.current || !markdown) return;
    if (!scrollToHeading && !scrollToPage) return;

    const rafId = requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!contentRef.current) return;

      if (scrollToHeading) {
        const headingId = generateHeadingId(scrollToHeading);
        const el = contentRef.current?.querySelector(`#${CSS.escape(headingId)}`) as HTMLElement | null;
        if (el) {
          scrollTo(el, "center");
          el.classList.add("bg-primary/10", "transition-colors");
          setTimeout(() => el.classList.remove("bg-primary/10"), 2000);
          return;
        }
      }

      if (scrollToPage) {
        const el = contentRef.current?.querySelector(`[data-page="${scrollToPage}"]`) as HTMLElement | null;
        if (el) {
          scrollTo(el, "start");
        }
      }
    }));

    return () => cancelAnimationFrame(rafId);
  }, [scrollToPage, scrollToHeading, markdown, scrollTo]);

  // ---- TOC heading click ----
  const handleTocSelect = useCallback((id: string) => {
    if (!contentRef.current) return;
    const el = contentRef.current.querySelector(`#${CSS.escape(id)}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveHeading(id);
    }
  }, []);

  // ---- Loading / error / empty states ----
  if (doc.status !== "indexed") return <ViewerEmpty />;
  if (isLoading) return <ViewerSkeleton />;
  if (error) return <ViewerError message={(error as Error).message} />;
  if (!markdown || markdown.trim().length === 0) return <ViewerEmpty />;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header bar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-shrink-0">
        <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
        <span className="text-sm font-medium text-gray-700 flex-1 truncate" title={doc.original_filename}>
          {doc.original_filename}
        </span>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-600"
            aria-label="Close viewer"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Content area */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {showToc && (
          <TOCSidebar
            headings={headings}
            activeId={activeHeading}
            onSelect={handleTocSelect}
          />
        )}

        <div
          ref={contentRef}
          className="flex-1 min-h-0 overflow-y-auto custom-scrollbar bg-white"
        >
          {headings.length > 0 && (
            <button
              onClick={() => setShowToc(!showToc)}
              className={cn(
                "sticky top-2 left-2 z-10 p-1.5 rounded-md border border-gray-200 bg-white/80 backdrop-blur-sm",
                "hover:bg-gray-50 transition-colors xl:hidden",
                "flex items-center gap-1 text-xs text-gray-500"
              )}
            >
              <List className="w-3.5 h-3.5" />
              <ChevronRight className={cn("w-3 h-3 transition-transform", showToc && "rotate-90")} />
            </button>
          )}

          <div className="max-w-3xl mx-auto my-6 px-8 md:px-12">
            {/* Document header */}
            <header className="mb-8 border-b border-gray-100 pb-6 text-center">
              <h2 className="text-xl font-bold text-primary mb-2">
                {doc.original_filename}
              </h2>
              {doc.page_count && (
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
                  {doc.page_count} Pages
                </p>
              )}
            </header>

            {/* Rendered markdown */}
            <article
              className={cn(
                "prose prose-sm max-w-none font-serif text-gray-800 leading-relaxed",
                "[&_h1]:text-xl [&_h1]:font-bold [&_h1]:mt-8 [&_h1]:mb-4 [&_h1]:scroll-mt-4 [&_h1]:text-primary",
                "[&_h2]:text-lg [&_h2]:font-bold [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:scroll-mt-4 [&_h2]:text-primary",
                "[&_h3]:text-base [&_h3]:font-bold [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:scroll-mt-4 [&_h3]:text-primary",
                "[&_h4]:text-sm [&_h4]:font-bold [&_h4]:mt-4 [&_h4]:mb-2 [&_h4]:scroll-mt-4 [&_h4]:text-primary",
                "[&_p]:mb-4 [&_p]:text-gray-700",
                "[&_li]:mb-1.5",
                "[&_strong]:text-primary [&_strong]:font-semibold",
                "[&_table]:w-full [&_table]:border-collapse [&_table]:text-sm [&_table]:my-6",
                "[&_th]:bg-gray-50 [&_th]:border [&_th]:border-gray-200 [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-semibold [&_th]:text-primary",
                "[&_td]:border [&_td]:border-gray-200 [&_td]:px-3 [&_td]:py-2 [&_td]:text-gray-600",
                "[&_blockquote]:border-l-4 [&_blockquote]:border-primary/20 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-gray-500 [&_blockquote]:my-6",
              )}
            >
              <ReactMarkdown
                remarkPlugins={remarkPlugins}
                rehypePlugins={rehypePlugins}
                components={mdComponents}
              >
                {processedMarkdown}
              </ReactMarkdown>
            </article>
          </div>
        </div>
      </div>
    </div>
  );
});
