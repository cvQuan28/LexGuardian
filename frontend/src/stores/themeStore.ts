import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ThemeState {
  isDark: boolean;
  toggle: () => void;
  setDark: (v: boolean) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      isDark: false,
      toggle: () =>
        set((s) => {
          const next = !s.isDark;
          applyTheme(next);
          return { isDark: next };
        }),
      setDark: (v) =>
        set(() => {
          applyTheme(v);
          return { isDark: v };
        }),
    }),
    { name: "lexguardian-theme" }
  )
);

function applyTheme(dark: boolean) {
  if (dark) {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

// Apply persisted theme on module load
const stored = localStorage.getItem("lexguardian-theme");
if (stored) {
  try {
    const { state } = JSON.parse(stored);
    if (state?.isDark) applyTheme(true);
  } catch {
    // ignore
  }
}
