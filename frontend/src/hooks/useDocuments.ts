import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Document } from "@/types";

export function useDocuments(workspaceId: number | null) {
  return useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => api.get<Document[]>(`/documents/workspace/${workspaceId}`),
    enabled: !!workspaceId,
  });
}

export function useUploadDocument(workspaceId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadFile<Document>(`/documents/upload/${workspaceId}`, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ docId, workspaceId }: { docId: number; workspaceId: number }) =>
      api.delete(`/documents/${docId}`).then(() => workspaceId),
    onSuccess: (workspaceId) => {
      qc.invalidateQueries({ queryKey: ["documents", workspaceId] });
    },
  });
}
