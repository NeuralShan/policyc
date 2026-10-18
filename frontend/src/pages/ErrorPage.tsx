import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link, isRouteErrorResponse, useRouteError } from "react-router";

import { Logo } from "../components/icons";
import { Button } from "../components/ui";

export function ErrorScreen({ title, detail, onRetry }: { title: string; detail?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-6 py-16 text-center">
      <Logo size={44} />
      <h1 className="mt-6 text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
      <p className="mt-2 text-sm leading-relaxed text-slate-600">
        Something went wrong on our side of the screen. Your data is safe: nothing was changed.
      </p>
      {detail && (
        <details className="mt-4 w-full rounded-lg bg-slate-100 p-3 text-left text-xs text-slate-700">
          <summary className="cursor-pointer font-medium">Technical details</summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words font-mono">{detail}</pre>
        </details>
      )}
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Button icon="refresh" onClick={onRetry ?? (() => window.location.reload())}>Try again</Button>
        <Link to="/"><Button variant="secondary" icon="arrowLeft">Back to home</Button></Link>
      </div>
    </div>
  );
}

/** Router-level errorElement: never shows React Router's default developer screen. */
export function RouteErrorPage() {
  const error = useRouteError();
  const detail = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? (error.stack ?? error.message)
      : String(error);
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  return (
    <ErrorScreen
      title={notFound ? "We could not find that page" : "This screen hit a problem"}
      detail={detail}
      onRetry={() => window.location.reload()}
    />
  );
}

/** Class boundary for render errors outside the router (providers, layout). */
export class RootErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
  }
  render() {
    if (this.state.error) {
      return (
        <ErrorScreen
          title="PolicyC hit a problem"
          detail={this.state.error.stack ?? this.state.error.message}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
