import { useEffect, useRef, useState } from "react";

import { api, type RunEvent } from "../api";

/**
 * Subscribes to a run's Server-Sent Events while `active`. Events are keyed by id, so the replay a
 * fresh connection receives (and EventSource's automatic reconnects) never produce duplicates.
 * The URL carries the Firebase id token as ?access_token because EventSource cannot set headers.
 */
export function useRunEvents(runId: string, active: boolean, onEnd: () => void) {
  const [events, setEvents] = useState<Map<number, RunEvent>>(new Map());
  const onEndRef = useRef(onEnd);
  onEndRef.current = onEnd;

  useEffect(() => {
    if (!active) return;
    let source: EventSource | undefined;
    let cancelled = false;
    void api.runEventsUrl(runId).then((url) => {
      if (cancelled) return;
      source = new EventSource(url);
      source.addEventListener("stage", (e) => {
        const event: RunEvent = JSON.parse((e as MessageEvent<string>).data);
        setEvents((prev) => new Map(prev).set(event.id, event));
      });
      source.addEventListener("end", () => {
        source?.close();
        onEndRef.current();
      });
    });
    return () => {
      cancelled = true;
      source?.close();
    };
  }, [runId, active]);

  return events;
}
