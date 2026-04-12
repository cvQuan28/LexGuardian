import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import type { AuthResponse, User } from "@/types";

export function useCurrentUser() {
  const token = useAuthStore((s) => s.token);
  const setUser = useAuthStore((s) => s.setUser);
  const setInitialized = useAuthStore((s) => s.setInitialized);

  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const user = await api.get<User>("/auth/me");
      setUser(user);
      setInitialized(true);
      return user;
    },
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60 * 1000,
    meta: { silent: true },
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: (data: { email: string; password: string }) =>
      api.post<AuthResponse>("/auth/login", data),
    onSuccess: (data) => {
      setSession(data.token, data.user);
      queryClient.invalidateQueries();
    },
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: (data: { email: string; password: string; display_name: string }) =>
      api.post<AuthResponse>("/auth/register", data),
    onSuccess: (data) => {
      setSession(data.token, data.user);
      queryClient.invalidateQueries();
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  const clearSession = useAuthStore((s) => s.clearSession);
  return useMutation({
    mutationFn: async () => {
      try {
        await api.post("/auth/logout");
      } finally {
        clearSession();
        queryClient.clear();
      }
    },
  });
}
