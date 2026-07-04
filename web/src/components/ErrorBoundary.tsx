"use client";

import { Component, type ReactNode, type ErrorInfo } from "react";

type Props = {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
};

type State = {
  hasError: boolean;
  error: Error | null;
};

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.props.onError?.(error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-6 backdrop-blur-sm text-center">
          <div className="text-2xl mb-2">⚠</div>
          <p className="text-sm text-gray-400 mb-1">Что-то пошло не так</p>
          <p className="text-xs text-gray-600 mb-3">{this.state.error?.message}</p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-1.5 rounded-lg text-xs font-medium bg-amber-400/20 text-amber-400 hover:bg-amber-400/30 transition"
          >
            Попробовать снова
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
