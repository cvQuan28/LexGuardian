import { useState } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { Scale, Home, MessageSquare, Library, ChevronDown, LogOut, Plus, Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import { useLogout } from "@/hooks/useAuth";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { KnowledgeBase } from "@/types";

interface SidebarProps {
  onWorkspaceSelect: (ws: KnowledgeBase) => void;
  collapsed?: boolean;
}

interface NavItem {
  label: string;
  icon: React.ElementType;
  to: string;
  matchPrefix?: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Command Center", icon: Home, to: "/" },
  { label: "Ask", icon: MessageSquare, to: "/ask", matchPrefix: "/ask" },
  { label: "Analyze", icon: Shield, to: "/analyze", matchPrefix: "/analyze" },
  { label: "Library", icon: Library, to: "/library", matchPrefix: "/library" },
];

export function Sidebar({ onWorkspaceSelect, collapsed = false }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { data: workspaces } = useWorkspaces();
  const { mutate: logout } = useLogout();
  const user = useAuthStore((s) => s.user);
  const activeWorkspace = useWorkspaceStore((s) => s.activeWorkspace);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false);

  function isActive(item: NavItem): boolean {
    if (item.matchPrefix) {
      return location.pathname.startsWith(item.matchPrefix);
    }
    return location.pathname === item.to;
  }

  function handleWorkspaceClick(ws: KnowledgeBase) {
    setActiveWorkspace(ws);
    onWorkspaceSelect(ws);
    setWorkspaceMenuOpen(false);
    navigate(`/ask/${ws.id}`);
  }

  const initials = user?.display_name
    ? user.display_name.slice(0, 2).toUpperCase()
    : user?.email?.slice(0, 2).toUpperCase() ?? "U";

  return (
    <aside
      className={cn(
        "flex flex-col h-full bg-primary text-primary-foreground",
        "transition-all duration-200",
        collapsed ? "w-14" : "w-56"
      )}
    >
      {/* Logo */}
      <div className={cn("flex items-center gap-2.5 px-4 py-5 border-b border-white/10", collapsed && "px-3 justify-center")}>
        <Scale className="w-5 h-5 text-white/80 flex-shrink-0" />
        {!collapsed && (
          <span className="text-sm font-bold tracking-tight text-white">LexGuardian</span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(item);
          return (
            <Link
              key={item.to}
              to={
                item.matchPrefix === "/ask" && activeWorkspace
                  ? `/ask/${activeWorkspace.id}`
                  : item.matchPrefix === "/analyze" && activeWorkspace
                  ? `/analyze/${activeWorkspace.id}`
                  : item.matchPrefix === "/library" && activeWorkspace
                  ? `/library/${activeWorkspace.id}`
                  : item.to
              }
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                active
                  ? "bg-white/15 text-white"
                  : "text-white/60 hover:bg-white/10 hover:text-white",
                collapsed && "justify-center px-2"
              )}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Workspace switcher */}
      {!collapsed && (
        <div className="px-2 py-3 border-t border-white/10">
          <p className="px-3 mb-1 text-[10px] font-semibold text-white/40 uppercase tracking-widest">
            Active Brief
          </p>
          <div className="relative">
            <button
              onClick={() => setWorkspaceMenuOpen((p) => !p)}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-white/80 hover:bg-white/10 hover:text-white transition-colors"
            >
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
              <span className="flex-1 text-left truncate text-xs">
                {activeWorkspace?.name ?? "Select a brief..."}
              </span>
              <ChevronDown className={cn("w-3 h-3 flex-shrink-0 transition-transform", workspaceMenuOpen && "rotate-180")} />
            </button>

            {workspaceMenuOpen && (
              <>
                {/* Backdrop to close on outside click */}
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setWorkspaceMenuOpen(false)}
                />
                <div className="absolute bottom-full left-0 right-0 mb-1 bg-white rounded-lg shadow-lg border border-gray-100 overflow-hidden z-50 max-h-48 overflow-y-auto">
                {(workspaces ?? []).length === 0 ? (
                  <p className="px-3 py-2 text-xs text-gray-400">No briefs yet</p>
                ) : (
                  (workspaces ?? []).map((ws) => (
                    <button
                      key={ws.id}
                      onClick={() => handleWorkspaceClick(ws)}
                      className={cn(
                        "w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-gray-50 transition-colors",
                        activeWorkspace?.id === ws.id ? "text-primary font-medium bg-primary/5" : "text-gray-700"
                      )}
                    >
                      <div className={cn(
                        "w-1.5 h-1.5 rounded-full flex-shrink-0",
                        activeWorkspace?.id === ws.id ? "bg-primary" : "bg-gray-300"
                      )} />
                      <span className="truncate">{ws.name}</span>
                    </button>
                  ))
                )}
                <div className="border-t border-gray-100">
                  <button
                    onClick={() => { setWorkspaceMenuOpen(false); navigate("/"); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-500 hover:bg-gray-50 transition-colors"
                  >
                    <Plus className="w-3 h-3" />
                    <span>New Brief</span>
                  </button>
                </div>
              </div>
            </>
            )}
          </div>
        </div>
      )}

      {/* User menu */}
      <div className={cn("px-2 py-3 border-t border-white/10", collapsed && "flex justify-center")}>
        {collapsed ? (
          <button
            onClick={() => logout()}
            className="p-2 rounded-lg text-white/60 hover:bg-white/10 hover:text-white transition-colors"
            title="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        ) : (
          <div className="flex items-center gap-2 px-2">
            <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-white truncate">
                {user?.display_name ?? user?.email ?? "User"}
              </p>
              <p className="text-[10px] text-white/50 truncate">{user?.email}</p>
            </div>
            <button
              onClick={() => logout()}
              className="p-1 rounded-md text-white/50 hover:bg-white/10 hover:text-white transition-colors flex-shrink-0"
              title="Sign out"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
