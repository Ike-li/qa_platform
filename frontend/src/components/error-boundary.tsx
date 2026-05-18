import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "./ui/button";
import i18n from "../i18n";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught app error:", error, errorInfo);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: undefined });
  };

  public render() {
    if (this.state.hasError) {
      return (
        <main className="flex min-h-screen w-full items-center justify-center bg-canvas px-4 text-ink">
          <section className="flex w-full max-w-md flex-col items-center rounded-xl border border-hairline bg-surface-1 p-8 text-center shadow-sm">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-status-failed/10 text-status-failed">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <h1 className="text-xl font-semibold tracking-tight">{i18n.t("errors.unexpectedTitle")}</h1>
            <p className="mt-2 text-sm text-ink-subtle">
              {i18n.t("errors.unexpectedDescription")}
            </p>
            {import.meta.env.DEV && this.state.error?.message && (
              <p className="mt-4 max-w-full truncate rounded-md border border-hairline bg-canvas px-3 py-2 font-mono text-xs text-ink-tertiary">
                {this.state.error.message}
              </p>
            )}
            <Button className="mt-6" onClick={this.handleRetry}>
              <RotateCcw className="mr-2 h-4 w-4" />
              {i18n.t("errors.retry")}
            </Button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
