"use client";

export default function ProtectedError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-8 backdrop-blur-sm text-center max-w-md">
        <div className="text-3xl mb-3">⚠</div>
        <h1 className="text-lg font-light text-white mb-2">Критическая ошибка</h1>
        <p className="text-sm text-gray-500 mb-4">
          {error.message || "Произошла непредвиденная ошибка"}
        </p>
        <button
          onClick={reset}
          className="px-5 py-2 rounded-lg text-sm font-medium bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 transition"
        >
          Попробовать снова
        </button>
      </div>
    </div>
  );
}
