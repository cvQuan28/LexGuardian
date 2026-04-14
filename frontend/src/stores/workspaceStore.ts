import { create } from "zustand";
import type { KnowledgeBase, Document, ChatSourceChunk } from "@/types";

interface SourceViewerState {
  open: boolean;
  document: Document | null;
  scrollToPage: number | null;
  scrollToHeading: string | null;
  highlightText: string | null;
}

interface WebSourceState {
  open: boolean;
  title: string;
  url: string;
  content: string;
  source_label: string;
}

interface WorkspaceState {
  activeWorkspace: KnowledgeBase | null;
  setActiveWorkspace: (ws: KnowledgeBase | null) => void;
  sourceViewer: SourceViewerState;
  openSourceViewer: (doc: Document, page: number | null, heading?: string | null, text?: string | null) => void;
  closeSourceViewer: () => void;
  webSource: WebSourceState;
  openWebSource: (source: { title: string; url: string; content: string; source_label?: string }) => void;
  closeWebSource: () => void;
  openCitation: (citation: ChatSourceChunk, documents: Document[]) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeWorkspace: null,
  setActiveWorkspace: (ws) => set({ activeWorkspace: ws }),
  sourceViewer: {
    open: false,
    document: null,
    scrollToPage: null,
    scrollToHeading: null,
    highlightText: null,
  },
  openSourceViewer: (doc, page, heading = null, text = null) =>
    set({
      sourceViewer: {
        open: true,
        document: doc,
        scrollToPage: page,
        scrollToHeading: heading,
        highlightText: text,
      },
      webSource: { open: false, title: "", url: "", content: "", source_label: "" },
    }),
  closeSourceViewer: () =>
    set((s) => ({ sourceViewer: { ...s.sourceViewer, open: false } })),
  webSource: {
    open: false,
    title: "",
    url: "",
    content: "",
    source_label: "",
  },
  openWebSource: (source) =>
    set({
      webSource: {
        open: true,
        title: source.title,
        url: source.url,
        content: source.content,
        source_label: source.source_label ?? "",
      },
      sourceViewer: {
        open: false,
        document: null,
        scrollToPage: null,
        scrollToHeading: null,
        highlightText: null,
      },
    }),
  closeWebSource: () =>
    set((s) => ({ webSource: { ...s.webSource, open: false } })),
  openCitation: (citation, documents) => {
    const isWeb = citation.source_scope === "web" || citation.document_id === 0;
    if (isWeb) {
      // Extract URL from citation.url or from chunk_id (format: web:{idx}:{url})
      const url = citation.url ||
        (citation.chunk_id?.startsWith("web:") ? citation.chunk_id.split(":").slice(2).join(":") : "");
      set({
        webSource: {
          open: true,
          title: citation.source_label || citation.heading_path?.[0] || "Nguồn web",
          url,
          content: citation.content,
          source_label: citation.source_label || "",
        },
        sourceViewer: {
          open: false,
          document: null,
          scrollToPage: null,
          scrollToHeading: null,
          highlightText: null,
        },
      });
      return;
    }
    const doc = documents.find((d) => d.id === citation.document_id);
    if (doc) {
      set({
        sourceViewer: {
          open: true,
          document: doc,
          scrollToPage: citation.page_no,
          scrollToHeading: citation.heading_path?.[0] ?? null,
          highlightText: citation.content?.slice(0, 120) ?? null,
        },
        webSource: { open: false, title: "", url: "", content: "", source_label: "" },
      });
    }
  },
}));
