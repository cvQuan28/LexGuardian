import { useState, useRef, useEffect } from "react";
import { Plus, X, Scale, Moon, Sun, LogOut, KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import { useCreateWorkspace } from "@/hooks/useWorkspaces";
import { useLogout, useChangePassword } from "@/hooks/useAuth";

interface TopBarProps {
  className?: string;
}

export function TopBar({ className }: TopBarProps) {
  const activeWorkspace = useWorkspaceStore((s) => s.activeWorkspace);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const user = useAuthStore((s) => s.user);
  const { isDark, toggle: toggleDark } = useThemeStore();
  const { mutateAsync: createWorkspace, isPending } = useCreateWorkspace();
  const logout = useLogout();
  const changePassword = useChangePassword();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newName, setNewName] = useState("");
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  const initials = user?.display_name
    ? user.display_name.slice(0, 2).toUpperCase()
    : user?.email?.slice(0, 2).toUpperCase() ?? "U";

  // Close menu on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    }
    if (showUserMenu) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showUserMenu]);

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

  async function handleChangePassword() {
    if (newPw !== confirmPw) {
      toast.error("Mật khẩu mới không khớp");
      return;
    }
    try {
      await changePassword.mutateAsync({ current_password: currentPw, new_password: newPw });
      toast.success("Đổi mật khẩu thành công");
      setShowChangePassword(false);
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Đổi mật khẩu thất bại";
      toast.error(msg.includes("không đúng") ? "Mật khẩu hiện tại không đúng" : "Đổi mật khẩu thất bại");
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

        {/* Right: actions + dark mode + avatar */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Dark mode toggle */}
          <button
            onClick={toggleDark}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
            aria-label={isDark ? "Chuyển sang sáng" : "Chuyển sang tối"}
            title={isDark ? "Chế độ sáng" : "Chế độ tối"}
          >
            {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>

          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            New Brief
          </button>

          {/* User avatar + dropdown */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setShowUserMenu((v) => !v)}
              className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-xs font-bold text-white hover:bg-primary/90 transition-colors"
              title={user?.display_name ?? user?.email}
            >
              {initials}
            </button>

            {showUserMenu && (
              <div className="absolute right-0 top-full mt-1.5 w-52 bg-white rounded-xl border border-gray-100 shadow-lg py-1 z-50">
                <div className="px-3 py-2 border-b border-gray-50">
                  <p className="text-xs font-semibold text-gray-800 truncate">{user?.display_name}</p>
                  <p className="text-[10px] text-gray-400 truncate">{user?.email}</p>
                </div>
                <button
                  onClick={() => { setShowUserMenu(false); setShowChangePassword(true); }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  <KeyRound className="w-3.5 h-3.5 text-gray-400" />
                  Đổi mật khẩu
                </button>
                <button
                  onClick={() => logout.mutate()}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-500 hover:bg-red-50 transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  Đăng xuất
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Change Password modal */}
      {showChangePassword && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold text-gray-900">Đổi mật khẩu</h2>
              <button
                onClick={() => { setShowChangePassword(false); setCurrentPw(""); setNewPw(""); setConfirmPw(""); }}
                className="p-1 rounded-md text-gray-400 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Mật khẩu hiện tại</label>
                <input
                  type="password"
                  value={currentPw}
                  onChange={(e) => setCurrentPw(e.target.value)}
                  autoFocus
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Mật khẩu mới</label>
                <input
                  type="password"
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  placeholder="Tối thiểu 8 ký tự"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Xác nhận mật khẩu mới</label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleChangePassword()}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                />
              </div>
              <div className="flex gap-2 justify-end pt-1">
                <button
                  onClick={() => { setShowChangePassword(false); setCurrentPw(""); setNewPw(""); setConfirmPw(""); }}
                  className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100 transition-colors"
                >
                  Hủy
                </button>
                <button
                  onClick={handleChangePassword}
                  disabled={!currentPw || !newPw || !confirmPw || changePassword.isPending}
                  className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {changePassword.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Lưu
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
                  Tên Brief
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
                  Hủy
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newName.trim() || isPending}
                  className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isPending ? "Đang tạo..." : "Tạo Brief"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
