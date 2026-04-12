import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { KnowledgeBase } from "@/types";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const navigate = useNavigate();
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const [mobileOpen, setMobileOpen] = useState(false);

  function handleWorkspaceSelect(ws: KnowledgeBase) {
    setActiveWorkspace(ws);
    navigate(`/ask/${ws.id}`);
    setMobileOpen(false);
  }

  return (
    <div className="flex h-screen overflow-hidden bg-surface-lowest">
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile Sidebar drawer */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 transition-transform duration-200 md:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <Sidebar onWorkspaceSelect={handleWorkspaceSelect} />
      </div>

      {/* Desktop Sidebar — fixed */}
      <div className="hidden md:flex flex-shrink-0">
        <Sidebar onWorkspaceSelect={handleWorkspaceSelect} />
      </div>

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Mobile hamburger + TopBar */}
        <div className="flex items-center md:hidden gap-2 px-2 h-12 bg-white border-b border-gray-100 flex-shrink-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="p-2 rounded-md text-gray-500 hover:bg-gray-100 transition-colors"
            aria-label="Open menu"
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          <TopBar className="flex-1 border-none h-auto px-0" />
        </div>

        {/* Desktop TopBar */}
        <div className="hidden md:block">
          <TopBar />
        </div>

        {/* Page content */}
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  );
}
