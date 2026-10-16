import { useEffect, useRef, useState } from "react";

import { api, type RunEvent } from "../api";

/**
 * Subscribes to a run's Server-Sent Events while `active`. Events are keyed by id, so the replay a
 * fresh connection receives (and EventSource's automatic reconnects) never produce duplicates.
 */
export function useRunEvents(runId: string, active: boolean, onEnd: () => void) {
  const [events, setEvents] = useState<Map<number, RunEvent>>(new Map());
  const onEndRef = useRef(onEnd);
  onEndRef.current = onEnd;

  useEffect(() => {
    if (!active) return;
    const source = new EventSource(api.runEventsUrl(runId));
    source.addEventListener("stage", (e) => {
      const event: RunEvent = JSON.parse((e as MessageEvent<string>).data);
      setEvents((prev) => new Map(prev).set(event.id, event));
    });
    source.addEventListener("end", () => {
      source.close();
      onEndRef.current();
    });
    return () => source.close();
  }, [runId, active]);

  return events;
}
