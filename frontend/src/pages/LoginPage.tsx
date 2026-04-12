import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Scale, Loader2, Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLogin, useRegister } from "@/hooks/useAuth";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useLogin();
  const register = useRegister();

  const isLoading = login.isPending || register.isPending;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    try {
      if (mode === "login") {
        await login.mutateAsync({ email, password });
      } else {
        await register.mutateAsync({ email, password, display_name: displayName });
      }
      navigate("/");
    } catch (err) {
      setError((err as Error).message || "Đã xảy ra lỗi. Vui lòng thử lại.");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-lowest px-4">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 rounded-full bg-primary/5" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 rounded-full bg-primary/3" />
      </div>

      <div className="relative w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-primary mb-4">
            <Scale className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-primary">LexGuardian</h1>
          <p className="text-sm text-gray-500 mt-1">AI Legal Copilot</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-ambient border border-gray-100 p-6">
          {/* Tab switcher */}
          <div className="flex gap-1 p-1 bg-surface-low rounded-lg mb-6">
            <button
              type="button"
              onClick={() => { setMode("login"); setError(null); }}
              className={cn(
                "flex-1 py-1.5 rounded-md text-sm font-medium transition-colors",
                mode === "login"
                  ? "bg-white text-primary shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              Đăng nhập
            </button>
            <button
              type="button"
              onClick={() => { setMode("register"); setError(null); }}
              className={cn(
                "flex-1 py-1.5 rounded-md text-sm font-medium transition-colors",
                mode === "register"
                  ? "bg-white text-primary shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              Đăng ký
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Tên hiển thị
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  required={mode === "register"}
                  placeholder="Nguyen Van A"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@example.com"
                autoComplete="email"
                className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Mật khẩu
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="••••••••"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  className="w-full px-3 py-2.5 pr-10 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((p) => !p)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="px-3 py-2 rounded-lg bg-red-50 border border-red-100">
                <p className="text-xs text-red-600">{error}</p>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
              {mode === "login" ? "Đăng nhập" : "Tạo tài khoản"}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-400 mt-4">
          {mode === "login" ? (
            <>Chưa có tài khoản?{" "}
              <button onClick={() => setMode("register")} className="text-primary hover:underline font-medium">
                Đăng ký ngay
              </button>
            </>
          ) : (
            <>Đã có tài khoản?{" "}
              <button onClick={() => setMode("login")} className="text-primary hover:underline font-medium">
                Đăng nhập
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
