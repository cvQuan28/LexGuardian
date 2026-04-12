import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Conversation } from "@/types";

export function useConversations(workspaceId: string) {
  return useQuery({
    queryKey: ["conversations", workspaceId],
    queryFn: () => api.get<Conversation[]>(`/conversations?workspace_id=${workspaceId}`),
    enabled: !!workspaceId,
  });
}

export function useCreateConversation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) =>
      api.post<Conversation>("/conversations", {
        workspace_id: Number(workspaceId),
        title,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });
    },
  });
}

export function useUpdateConversation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api.patch<Conversation>(`/conversations/${id}`, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });
    },
  });
}

export function useDeleteConversation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/conversations/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["chat-history", workspaceId] });
    },
  });
}
