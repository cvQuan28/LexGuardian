import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { useAuthStore } from "@/stores/authStore";
import { useCurrentUser } from "@/hooks/useAuth";
import { AppShell } from "@/components/layout/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { CommandCenterPage } from "@/pages/CommandCenterPage";
import { AskPage } from "@/pages/AskPage";
import { AnalyzePage } from "@/pages/AnalyzePage";
import { LibraryPage } from "@/pages/LibraryPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

function AuthGate({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const initialized = useAuthStore((s) => s.initialized);
  useCurrentUser(); // fetches /auth/me on mount when token exists
  if (!token) return <Navigate to="/login" replace />;
  if (!initialized) return null; // wait for auth check
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Toaster position="top-right" richColors />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <AuthGate>
                <AppShell>
                  <CommandCenterPage />
                </AppShell>
              </AuthGate>
            }
          />
          <Route
            path="/ask/:workspaceId"
            element={
              <AuthGate>
                <AppShell>
                  <AskPage />
                </AppShell>
              </AuthGate>
            }
          />
          <Route
            path="/analyze/:workspaceId"
            element={
              <AuthGate>
                <AppShell>
                  <AnalyzePage />
                </AppShell>
              </AuthGate>
            }
          />
          <Route
            path="/library/:workspaceId"
            element={
              <AuthGate>
                <AppShell>
                  <LibraryPage />
                </AppShell>
              </AuthGate>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
