import { create } from "zustand";
import { getStoredAuthToken, setStoredAuthToken } from "@/lib/api";
import type { User } from "@/types";

interface AuthState {
  token: string | null;
  user: User | null;
  initialized: boolean;
  setSession: (token: string, user: User) => void;
  clearSession: () => void;
  setUser: (user: User | null) => void;
  setInitialized: (value: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: getStoredAuthToken(),
  user: null,
  initialized: false,
  setSession: (token, user) => {
    setStoredAuthToken(token);
    set({ token, user, initialized: true });
  },
  clearSession: () => {
    setStoredAuthToken(null);
    set({ token: null, user: null, initialized: true });
  },
  setUser: (user) => set({ user }),
  setInitialized: (value) => set({ initialized: value }),
}));
