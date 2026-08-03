import { describe, it, expect, beforeEach } from "vitest";
import { useActivityStore, toActivityEvent } from "./activityStore";

describe("activityStore", () => {
  beforeEach(() => {
    useActivityStore.getState().clear();
  });

  it("adds an event to the front of the list", () => {
    useActivityStore.getState().addEvent({ event_type: "ServerStartedEvent", name: "A", timestamp: 100 });
    useActivityStore.getState().addEvent({ event_type: "ServerStoppedEvent", name: "B", timestamp: 200 });
    const events = useActivityStore.getState().events;
    expect(events).toHaveLength(2);
    expect(events[0].name).toBe("B");
  });

  it("caps the list at 20 events", () => {
    const store = useActivityStore.getState();
    for (let i = 0; i < 25; i++) {
      store.addEvent({ event_type: "ServerStartedEvent", timestamp: i });
    }
    expect(useActivityStore.getState().events).toHaveLength(20);
  });

  it("replaces events via setEvents", () => {
    useActivityStore.getState().addEvent({ event_type: "ServerStartedEvent", timestamp: 1 });
    useActivityStore.getState().setEvents([
      { event_type: "ServerCrashedEvent", timestamp: 2 },
      { event_type: "ServerStoppedEvent", timestamp: 3 },
    ]);
    const events = useActivityStore.getState().events;
    expect(events.map((e) => e.event_type)).toEqual(["ServerCrashedEvent", "ServerStoppedEvent"]);
  });

  it("clears all events", () => {
    useActivityStore.getState().addEvent({ event_type: "ServerStartedEvent", timestamp: 1 });
    useActivityStore.getState().clear();
    expect(useActivityStore.getState().events).toHaveLength(0);
  });

  it("normalizes raw websocket events", () => {
    const event = toActivityEvent({
      event_type: "ServerStartedEvent",
      server_id: "srv-1",
      name: "My Server",
      timestamp: 1234.5,
    });
    expect(event.event_type).toBe("ServerStartedEvent");
    expect(event.server_id).toBe("srv-1");
    expect(event.name).toBe("My Server");
    expect(event.timestamp).toBe(1234.5);
  });
});
