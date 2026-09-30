import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

print("AT-SPI import OK")
desktop = Atspi.get_desktop(0)
print("applications:", desktop.get_child_count())
for i in range(min(desktop.get_child_count(), 20)):
    app = desktop.get_child_at_index(i)
    try:
        print(i, app.get_name())
    except Exception as exc:
        print(i, "<error>", exc)
