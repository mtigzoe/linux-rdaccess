"""One fixed simulated message-route entry point; no raw routing fallback."""

from types import SimpleNamespace

import braille
import inputCore


def queueMessageRoute(bridge, permitted):
	"""Called on NVDA's GUI thread under a separately granted one-shot permission.

	Enters the same ownership-guarded queue branch used by a routing gesture.
	It bypasses hardware, driver binding and the global gesture decider chain.
	"""
	if permitted() is not True or bridge is None:
		return "refused"
	manager = getattr(inputCore, "manager", None)
	client = bridge._client
	if (
		manager is None
		or getattr(manager, "_captureFunc", None) is not None
		or getattr(manager, "isInputHelpActive", False)
		or client is None
		or not getattr(client, "sendingKeys", False)
		or not bridge._semanticBrailleInputInstalled
		or not bridge._outcomesActive()
	):
		return "refused"
	# Stock message regions are inert text. Do not activate an add-on's custom
	# region through this narrow test permission, even if it supports weakrefs.
	regions = tuple(getattr(getattr(braille.handler, "messageBuffer", None), "regions", ()))
	regionType = getattr(braille, "TextRegion", None)
	if not regions or any(type(region) is not regionType for region in regions):
		return "refused"
	gesture = SimpleNamespace(routingIndex=0)
	# Do not delegate to native main-buffer/raw routing if the message vanished.
	# The shared queued branch revalidates both ownership and consent at execution.
	queued = bridge._queueOwnedMessageRoute(gesture, testPermit=permitted)
	return "queued" if queued else "refused"
