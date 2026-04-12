import { create } from "zustand";
import type { KnowledgeBase, Document, ChatSourceChunk } from "@/types";

interface SourceViewerState {
  open: boolean;
  document: Document | null;
  scrollToPage: number | null;
  scrollToHeading: string | null;
  highlightText: string | null;
}

interface WorkspaceState {
  activeWorkspace: KnowledgeBase | null;
  setActiveWorkspace: (ws: KnowledgeBase | null) => void;
  sourceViewer: SourceViewerState;
  openSourceViewer: (doc: Document, page: number | null, heading?: string | null, text?: string | null) => void;
  closeSourceViewer: () => void;
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
    }),
  closeSourceViewer: () =>
    set((s) => ({ sourceViewer: { ...s.sourceViewer, open: false } })),
  openCitation: (citation, documents) => {
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
      });
    }
  },
}));
