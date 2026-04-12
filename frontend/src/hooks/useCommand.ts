import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CommandIntent } from "@/types";

export function useDetectIntent(workspaceId: number | null) {
  return useMutation({
    mutationFn: (input: string) =>
      api.post<CommandIntent>(`/command/detect-intent/${workspaceId}`, { input }),
    retry: false,
  });
}
