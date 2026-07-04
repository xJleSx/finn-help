import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-light tracking-tight">
            Fin<span className="text-amber-400 font-medium">Advisor</span>
          </h1>
          <p className="text-gray-500 text-sm mt-1">AI финансовый ассистент для MOEX</p>
        </div>
        <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
          {children}
        </div>
      </div>
    </div>
  );
}
