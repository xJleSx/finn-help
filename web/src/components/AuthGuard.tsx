"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !token) {
      router.replace("/login");
    }
  }, [token, isLoading, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="animate-pulse text-gray-500">Загрузка...</div>
      </div>
    );
  }

  if (!token) {
    return null;
  }

  return <>{children}</>;
}
