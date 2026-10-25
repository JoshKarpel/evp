# `sys.UnraisableHookArgs` exists only in typeshed, so the annotations naming it mustn't be
# evaluated, which Python 3.13 does eagerly without this.
from __future__ import annotations

import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest

from evp import (
    DeviceAttributes,
    Formatter,
    KeyEncoder,
    MouseEncoder,
    RenderState,
    Terminal,
)


@pytest.fixture
def unraisables(monkeypatch: pytest.MonkeyPatch) -> list[sys.UnraisableHookArgs]:
    """Every exception raised where Python can't propagate it, such as in a destructor."""
    caught: list[sys.UnraisableHookArgs] = []
    monkeypatch.setattr(sys, "unraisablehook", caught.append)
    return caught


def run_on_another_thread[T](function: Callable[[], T]) -> T:
    """Run `function` on a fresh thread, re-raising anything it raises."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(function).result()


def written_terminal() -> Terminal:
    terminal = Terminal(10, 3, max_scrollback_bytes=1_000_000, on_bell=lambda: None)
    terminal.feed(b"\x1b[31mone\r\ntwo\r\nthree\r\nfour")
    return terminal


def read_frame() -> object:
    terminal = written_terminal()
    return RenderState(terminal).frame()


@pytest.mark.parametrize(
    "build",
    [
        written_terminal,
        lambda: RenderState(written_terminal()),
        read_frame,
        lambda: RenderState(written_terminal()).scrolled_off(),
        lambda: RenderState(written_terminal()).history(),
        lambda: KeyEncoder(written_terminal()),
        lambda: MouseEncoder(written_terminal()),
        lambda: Formatter(written_terminal()),
        DeviceAttributes,
    ],
)
def test_dropping_on_another_thread_raises_nothing(
    build: Callable[[], object], unraisables: list[sys.UnraisableHookArgs]
) -> None:
    # Only the list holds the object, so clearing it on the other thread drops it there.
    holder = [build()]

    run_on_another_thread(holder.clear)

    assert unraisables == []


def test_terminal_written_on_one_thread_reads_on_another() -> None:
    terminal = written_terminal()
    state = RenderState(terminal)

    rows = run_on_another_thread(lambda: state.frame().rows)

    assert "".join(rows[-1].graphemes).rstrip() == "four"


def test_render_state_dropped_on_another_thread_frees_its_terminal() -> None:
    terminal = written_terminal()
    holder = [RenderState(terminal)]

    run_on_another_thread(holder.clear)

    assert not terminal.is_rendered


def test_callback_raising_on_another_thread_raises_from_feed_there() -> None:
    def fail() -> None:
        msg = "no bell"
        raise KeyError(msg)

    terminal = Terminal(10, 3, on_bell=fail)

    with pytest.raises(KeyError, match="no bell"):
        run_on_another_thread(lambda: terminal.feed(b"\x07"))
