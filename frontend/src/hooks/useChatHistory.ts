import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChatHistoryResponse } from "@/types";

export function useChatHistory(workspaceId: string, conversationId?: number | null) {
  return useQuery({
    queryKey: ["chat-history", workspaceId, conversationId ?? "none"],
    queryFn: () =>
      api.get<ChatHistoryResponse>(
        `/rag/chat/${workspaceId}/history${conversationId ? `?conversation_id=${conversationId}` : ""}`
      ),
    enabled: !!workspaceId,
    staleTime: Infinity, // Don't auto-refetch — we invalidate manually after chat
  });
}

export function useClearChatHistory(workspaceId: string, conversationId?: number | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      api.delete(`/rag/chat/${workspaceId}/history${conversationId ? `?conversation_id=${conversationId}` : ""}`),
    onSuccess: () => {
      queryClient.setQueryData<ChatHistoryResponse>(
        ["chat-history", workspaceId, conversationId ?? "none"],
        {
          workspace_id: Number(workspaceId),
          conversation_id: conversationId ?? null,
          messages: [],
          total: 0,
        },
      );
    },
  });
}
