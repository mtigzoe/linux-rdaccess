# Semantic object action error audit — 2026-10-09

## Expected

One NVDA-origin semantic activation request should attempt one provider action.
An error should fail that request without activating the same control through
another API spelling. A fresh explicit request should remain usable. See the
[behavior contract](../.github/NVDA_LINUX_BEHAVIOR.md).

## Native reference

Followed [Orca source references](../.github/ORCA_SOURCE_REFERENCES.md).
Installed Orca reports `42.0`, package `42.0-1ubuntu2`; installed pyatspi is
`2.38.2-1` and the AT-SPI typelib package is `2.44.0-3`.

Inspected installed `braille.Component.processRoutingKey` and
`pyatspi.Action.doAction`. Native component routing calls `doAction(0)` once;
the pyatspi method delegates once to `Atspi.Action.do_action`. Retrieved the
official pinned [Orca 42.3 braille source](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/braille.py)
and verified that its component routing method's AST matches the installed
method. This comparison establishes equivalence of that method only.

The official [AT-SPI action API](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Action.do_action.html)
describes an invocation with a success result and a recoverable error. The
bridge supports both modern `do_action` and legacy `doAction` spellings. They
represent the same operation, so selecting another spelling after an invocation
error can issue a second activation; an error does not prove the first attempt
had no effect.

## Confirmed defects — automated-tested

`a11y_model.perform_action` continued to the legacy alias when an available
modern action method raised. A provider fixture exposing both supported APIs
demonstrates two outcomes: an exception after activation repeats the activation,
and an exception before activation invokes the other alias and reports success.
The semantic Orca adapter and real loopback TCP controller reproduce these
outcomes with one `lrd_a11y_action` request.

Seven added regression/control methods run against the genuine model from main
`8412a42` produce five assertion failures, zero errors and zero skips. The
explicit-False and missing-modern-method controls already pass on that baseline.

## Implemented (code-reviewed)

An exception from the first available action method now returns failure.
Choosing a legacy method when the modern method is absent/noncallable remains
supported; explicit rejection still fails without retry. Successful actions,
index validation and focus/session guards retain their existing behavior.

Tests also verify that a failed action retains its current semantic context and
that a fresh explicit request works without reconnecting. Provider exception
details stay out of controller logs.

## Automated-tested validation

| Coverage | Result |
| --- | --- |
| Existing braille matrix contract | 112 tests passed |
| Existing remote-protocol matrix contract | 41 tests passed |
| Model, control patterns, GI accessors, speech/braille bridge and installed CLI | 83 tests passed |

These are 236 distinct focused methods under Python 3.10.12, with no final
failures or skips. Five new unit methods and two TCP methods are in suites
already selected by the compatibility matrix; its inventory requires no change.
The unchanged keyboard/browse and speech/focus matrix groups were not rerun.

A private reinstall replaced the genuine prior standalone model with the fixed
source, preserved original controller/configuration backups and 0600
permissions, copied both runtime modules and remained idempotent. The installed
adapter/model passed single-attempt failure and fresh-request checks. Generated
Python compilation and Python 3.10 grammar passed. The v116 controller is
unchanged: the installer already copies the standalone model on every update,
so no controller marker change is needed. No real configuration was modified.

Exact matrix inventory, distinct test IDs, changed Python compilation, root
Python wrapper preservation and whitespace checks passed.

## Known issue / not verified

The reproductions use a fixture exposing both supported action APIs. Installed
pyatspi's standard Action wrapper exposes the legacy spelling; no duplicate
activation was reproduced in a live Linux application or a real provider
exposing both APIs. The confirmed evidence is the model/adapter behavior and
controller dispatch through actual loopback TCP.

Windows NVDA output, audible speech, physical braille, real application acceptance
and other Orca versions remain unverified. No graphical display is available;
the opt-in speech probe was not enabled. Restart Orca after reinstalling to load
the updated standalone model. GitHub Actions were not queried or monitored, and
no merge was performed.
