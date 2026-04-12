import { useState } from "react";
import { Plus, X, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useAuthStore } from "@/stores/authStore";
import { useCreateWorkspace } from "@/hooks/useWorkspaces";

interface TopBarProps {
  className?: string;
}

export function TopBar({ className }: TopBarProps) {
  const activeWorkspace = useWorkspaceStore((s) => s.activeWorkspace);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const user = useAuthStore((s) => s.user);
  const { mutateAsync: createWorkspace, isPending } = useCreateWorkspace();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newName, setNewName] = useState("");

  const initials = user?.display_name
    ? user.display_name.slice(0, 2).toUpperCase()
    : user?.email?.slice(0, 2).toUpperCase() ?? "U";

  async function handleCreate() {
    const trimmed = newName.trim();
    if (!trimmed) return;
    try {
      const ws = await createWorkspace({ name: trimmed });
      setActiveWorkspace(ws);
      setShowCreateModal(false);
      setNewName("");
    } catch {
      // Error handled by toast
    }
  }

  return (
    <>
      <header
        className={cn(
          "h-12 flex items-center justify-between px-4 bg-white border-b border-gray-100 flex-shrink-0",
          className
        )}
      >
        {/* Left: workspace name */}
        <div className="flex items-center gap-2 min-w-0">
          <Scale className="w-4 h-4 text-primary/40 flex-shrink-0" />
          {activeWorkspace ? (
            <span className="text-sm font-medium text-gray-700 truncate">
              {activeWorkspace.name}
            </span>
          ) : (
            <span className="text-sm text-gray-400">LexGuardian</span>
          )}
        </div>

        {/* Right: actions + avatar */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            New Brief
          </button>

          <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-xs font-bold text-white">
            {initials}
          </div>
        </div>
      </header>

      {/* Create Brief modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold text-gray-900">New Brief</h2>
              <button
                onClick={() => { setShowCreateModal(false); setNewName(""); }}
                className="p-1 rounded-md text-gray-400 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Brief name
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                  placeholder="e.g., NDA Review Q4 2024"
                  autoFocus
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => { setShowCreateModal(false); setNewName(""); }}
                  className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newName.trim() || isPending}
                  className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isPending ? "Creating..." : "Create Brief"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
