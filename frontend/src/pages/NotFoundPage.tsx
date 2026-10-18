import { Link } from "react-router";

import { Button, EmptyState } from "../components/ui";

export function NotFoundPage() {
  return (
    <EmptyState title="Page not found" art="search" action={<Link to="/"><Button>Back to home</Button></Link>}>
      That address does not match anything in PolicyC.
    </EmptyState>
  );
}
