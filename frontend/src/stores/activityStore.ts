import { create } from "zustand";

export interface ActivityEvent {
  id: string;
  event_type: string;
  server_id?: string;
  name?: string;
  message?: string;
  timestamp: number;
}

interface ActivityState {
  events: ActivityEvent[];
  addEvent: (event: Omit<ActivityEvent, "id">) => void;
  setEvents: (events: Omit<ActivityEvent, "id">[]) => void;
  clear: () => void;
}

const MAX_EVENTS = 20;

let nextId = 1;

function normalize(event: Omit<ActivityEvent, "id">): ActivityEvent {
  return {
    ...event,
    id: `activity-${nextId++}`,
  };
}

export const useActivityStore = create<ActivityState>((set) => ({
  events: [],
  addEvent: (event) =>
    set((state) => ({
      events: [normalize(event), ...state.events].slice(0, MAX_EVENTS),
    })),
  setEvents: (events) =>
    set({ events: events.map(normalize).slice(0, MAX_EVENTS) }),
  clear: () => set({ events: [] }),
}));

export function toActivityEvent(raw: Record<string, unknown>): Omit<ActivityEvent, "id"> {
  const eventType = (raw.event_type as string) ?? "UnknownEvent";
  let ts: number;
  if (typeof raw.timestamp === "number" && !Number.isNaN(raw.timestamp)) {
    ts = raw.timestamp > 1e11 ? raw.timestamp / 1000 : raw.timestamp;
  } else if (typeof raw.timestamp === "string") {
    const parsed = Number(raw.timestamp);
    if (!Number.isNaN(parsed)) {
      ts = parsed > 1e11 ? parsed / 1000 : parsed;
    } else {
      const dateMs = Date.parse(raw.timestamp);
      ts = !Number.isNaN(dateMs) ? dateMs / 1000 : Date.now() / 1000;
    }
  } else {
    ts = Date.now() / 1000;
  }

  return {
    event_type: eventType,
    server_id: (raw.server_id as string) ?? undefined,
    name: (raw.name as string) ?? undefined,
    message: (raw.message as string) ?? undefined,
    timestamp: ts,
  };
}
