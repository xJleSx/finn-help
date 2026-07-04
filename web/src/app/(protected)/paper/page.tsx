"use client";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { PaperDashboard } from "@/components/PaperDashboard";

export default function PaperPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-light text-white">Paper Trading</h1>
        <p className="text-sm text-gray-500 mt-1">Симуляция торговли без реальных денег</p>
      </div>
      <ErrorBoundary>
        <PaperDashboard />
      </ErrorBoundary>
    </div>
  );
}
