import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

def cb(event, data=None):
    print("EVENT", event.type, flush=True)

listener=Atspi.EventListener.new(cb)
for t in [
    "object:state-changed:focused",
    "object:active-descendant-changed",
    "object:property-change:accessible-name",
    "window:activate",
    "window:deactivate",
    "object",
    "window",
]:
    try:
        print("REGISTER", t, listener.register(t), flush=True)
    except Exception as e:
        print("REGISTER-ERR", t, repr(e), flush=True)
loop=GLib.MainLoop()
GLib.timeout_add_seconds(3, lambda:(loop.quit(),False)[1])
loop.run()
