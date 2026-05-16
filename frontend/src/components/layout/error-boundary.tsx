import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "../ui/button";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-[50vh] w-full flex-col items-center justify-center rounded-xl border border-hairline bg-surface-1 p-8 text-center shadow-sm">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-status-failed/10 text-status-failed mb-4">
            <AlertCircle className="h-6 w-6" />
          </div>
          <h2 className="text-lg font-semibold text-ink">Something went wrong</h2>
          <p className="mt-2 max-w-md text-sm text-ink-subtle">
            {this.state.error?.message || "An unexpected error occurred while rendering this section."}
          </p>
          <Button 
            className="mt-6" 
            variant="outline"
            onClick={() => this.setState({ hasError: false })}
          >
            Try again
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
