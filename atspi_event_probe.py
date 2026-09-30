import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

def on_event(event, data=None):
    try:
        src = event.source
        print(event.type, repr(src.get_name()), src.get_role_name(), flush=True)
    except Exception as exc:
        print(event.type, "ERROR", exc, flush=True)

listener = Atspi.EventListener.new(on_event)
for event_type in (
    "object:state-changed:focused",
    "object:active-descendant-changed",
    "object:property-change:accessible-name",
    "window:activate",
    "window:deactivate",
):
    listener.register(event_type)

print("EVENT PROBE READY", flush=True)
loop = GLib.MainLoop()
GLib.timeout_add_seconds(12, lambda: (loop.quit(), False)[1])
loop.run()
print("EVENT PROBE DONE", flush=True)
