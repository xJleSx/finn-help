"use client";

import { Component, type ReactNode, type ErrorInfo } from "react";

interface Props {
  name: string;
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class CardErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.name}]`, error.message, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6">
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="text-2xl">⚠</span>
            <p className="text-sm font-medium text-red-500">Ошибка загрузки</p>
            <p className="text-xs text-muted-foreground">{this.props.name}</p>
            <button
              type="button"
              onClick={() => this.setState({ hasError: false })}
              className="mt-2 rounded-md bg-red-500/10 px-3 py-1 text-xs font-medium text-red-500 transition-colors hover:bg-red-500/20"
            >
              Повторить
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
