import { Link } from "react-router";

import { PageHeader } from "../components/Layout";

export function NotFoundPage() {
  return (
    <PageHeader
      title="Page not found"
      subtitle={
        <Link to="/" className="hover:text-slate-900 hover:underline">
          Back to projects
        </Link>
      }
    />
  );
}
