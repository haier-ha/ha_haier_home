"""Per-target command debouncer shared by the climate and scene platforms.

See ``docs/command-debounce-design.md`` for the full rationale. In short this
merges bursts of downstream commands so the cloud/device is not hammered by
rapid taps (temperature +/-, mode toggles) or accidental double-taps on a
scene, while guaranteeing the user's final intent is always delivered.

Two modes, selected by ``trailing`` and by the command *semantics* (not the
platform):

* ``trailing=True`` (climate, and any future stateful attribute platform):
  leading + trailing. The first command in an idle window fires immediately
  for instant UI feedback; commands arriving inside the window are merged per
  attribute key (later value wins) and flushed once when the window closes.
  Nothing is ever dropped, so optimistic entity state is always eventually
  confirmed.

* ``trailing=False`` (scenes, and any future stateless one-shot action): the
  first command fires immediately; repeats inside the window are swallowed and
  never replayed. This matches the "prevent accidental double-trigger" intent
  for stateless actions whose replay has a real-world cost.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later


class CommandDebouncer:
    """Merge / throttle bursts of commands per bucket key."""

    def __init__(
        self,
        hass: HomeAssistant,
        delay_ms: int,
        send: Callable[[str, dict[str, Any]], Awaitable[bool]],
        *,
        trailing: bool = True,
    ) -> None:
        """Initialise the debouncer.

        Args:
            hass: Home Assistant instance (for scheduling timers).
            delay_ms: Debounce window length in milliseconds.
            send: Coroutine actually performing the send, called as
                ``send(key, commands)`` and returning success as a bool.
            trailing: ``True`` for leading + trailing merge (stateful
                attributes); ``False`` for leading-only (stateless one-shots).
        """
        self._hass = hass
        self._delay = delay_ms / 1000.0
        self._send = send
        self._trailing = trailing
        self._pending: dict[str, dict[str, Any]] = {}
        self._unsubs: dict[str, Callable[[], None]] = {}

    async def async_submit(self, key: str, commands: dict[str, Any]) -> bool:
        """Submit a command for ``key``.

        On the leading edge (idle window) the command is sent immediately and
        its result returned. While a window is open, trailing-mode submissions
        are merged per attribute key (accepted, returns ``True``) and
        leading-only submissions are swallowed (accepted, returns ``True``).

        HA runs a single-threaded event loop and there is no ``await`` between
        the window check and mutating ``_unsubs``/``_pending``, so no lock is
        needed.
        """
        if key not in self._unsubs:
            # Window idle: fire immediately (leading edge), then open a window.
            self._open_window(key)
            return await self._send(key, commands)

        if not self._trailing:
            # leading-only (scenes): swallow repeats inside the window.
            return True

        # leading + trailing: accumulate by attribute key (later value wins).
        self._pending.setdefault(key, {}).update(commands)
        return True

    @callback
    def _open_window(self, key: str) -> None:
        """Open (or reopen) the debounce window for ``key``."""
        # ``partial`` of a @callback-decorated method is detected by HA as a
        # CALLBACK job, so the timer fires on the event loop (never in an
        # executor thread, which would make async_create_task unsafe).
        self._unsubs[key] = async_call_later(
            self._hass,
            self._delay,
            partial(self._on_window_elapsed, key),
        )

    @callback
    def _on_window_elapsed(self, key: str, _now: Any) -> None:
        """Timer callback: schedule the flush coroutine on the event loop."""
        self._hass.async_create_task(self._flush(key))

    async def _flush(self, key: str) -> None:
        """Flush any pending merged commands when the window closes."""
        self._unsubs.pop(key, None)
        merged = self._pending.pop(key, None)
        if merged:
            # Keep throttling while the burst continues.
            self._open_window(key)
            await self._send(key, merged)

    @callback
    def async_cancel(self) -> None:
        """Cancel all pending timers and drop pending commands (on unload)."""
        for unsub in self._unsubs.values():
            unsub()
        self._unsubs.clear()
        self._pending.clear()
