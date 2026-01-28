"""sclang event tracer — runs a generated .scd through sclang and extracts events.

This module provides feedback on what a generated .scd file actually produces
when evaluated by SuperCollider, without requiring audio playback.

Usage:
    events = trace_scd_file("output.scd", start_symbol="S", max_events=200)
    for e in events:
        print(e)  # {'type': 'note', 'midinote': 60, 'dur': 0.25, ...}
"""

from __future__ import annotations

import re
import subprocess
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TraceEvent:
    """A single event extracted from sclang trace output."""
    index: int
    type: str  # "note" or "rest"
    midinote: float | None = None
    dur: float | None = None
    stretch: float | None = None
    ctranspose: float | None = None
    detune: float | None = None


def sclang_available() -> bool:
    """Check if sclang is available on the system."""
    return shutil.which("sclang") is not None


def trace_scd_content(scd_content: str, start_symbol: str = "S",
                      max_events: int = 200,
                      timeout: float = 30.0) -> list[TraceEvent]:
    """Trace events produced by .scd content through sclang.

    Writes the .scd content to a temp file (with .play commented out),
    then runs a separate trace script that uses executeFile to load the
    definitions and manually pulls events from the stream.

    Args:
        scd_content: The full .scd file content.
        start_symbol: The Pdef symbol to trace (default "S").
        max_events: Maximum events to extract.
        timeout: sclang process timeout in seconds.

    Returns:
        List of TraceEvent objects representing the event sequence.

    Raises:
        RuntimeError: If sclang is not available or fails.
    """
    if not sclang_available():
        raise RuntimeError("sclang not found in PATH")

    # Write the scd content to a temp file, commenting out the .play call
    # so definitions are loaded without starting playback
    modified = scd_content.replace(
        f"Pdef(\\{start_symbol}).play;",
        f"// Pdef(\\{start_symbol}).play;  // commented by tracer",
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".scd", delete=False, encoding="utf-8"
    ) as scd_f:
        scd_f.write(modified)
        scd_path = scd_f.name

    trace_script = _build_trace_script(scd_path, start_symbol, max_events)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".scd", delete=False, encoding="utf-8"
    ) as trace_f:
        trace_f.write(trace_script)
        trace_path = trace_f.name

    try:
        result = subprocess.run(
            ["sclang", trace_path],
            capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"sclang timed out after {timeout}s")
    finally:
        Path(trace_path).unlink(missing_ok=True)
        Path(scd_path).unlink(missing_ok=True)

    return _parse_trace_output(output)


def trace_scd_file(scd_path: str | Path, start_symbol: str = "S",
                   max_events: int = 200,
                   timeout: float = 30.0) -> list[TraceEvent]:
    """Trace events from a .scd file."""
    content = Path(scd_path).read_text(encoding="utf-8")
    return trace_scd_content(content, start_symbol, max_events, timeout)


def _build_trace_script(scd_path: str, start_symbol: str,
                        max_events: int) -> str:
    """Build a sclang script that loads a .scd file and extracts events.

    Uses executeFile to load the definitions from scd_path (which should
    have .play commented out), then manually pulls events from the stream.
    This avoids any fragile content-stripping of parentheses.
    """
    # Escape backslashes in the path for SC string literal
    escaped_path = scd_path.replace("\\", "\\\\")

    return f"""
"===LOADING===".postln;
thisProcess.interpreter.executeFile("{escaped_path}");
"===LOADED===".postln;

Pdef.all.do(_.stop);

"===TRACE_START===".postln;
{{
    var stream, event, maxEvents = {max_events};
    stream = Pdef(\\{start_symbol}).asStream;
    maxEvents.do {{ |i|
        event = stream.next(Event.default);
        if(event.isNil) {{
            "===STREAM_END=== after % events".format(i).postln;
            0.exit;
        }};
        if(event[\\dur].isKindOf(Rest)) {{
            "BP2SC_EVENT %: type=rest dur=% stretch=%".format(
                i, event[\\dur].value, event[\\stretch] ?? 1.0
            ).postln;
        }} {{
            "BP2SC_EVENT %: type=note midinote=% dur=% stretch=% ctranspose=% detune=%".format(
                i,
                event[\\midinote].value,
                event[\\dur],
                event[\\stretch] ?? 1.0,
                event[\\ctranspose] ?? 0.0,
                event[\\detune] ?? 0.0
            ).postln;
        }};
    }};
    "===TRACE_END=== (max % events)".format(maxEvents).postln;
    0.exit;
}}.value;
"""


# Regex for parsing trace output lines
_RE_NOTE = re.compile(
    r"BP2SC_EVENT (\d+): type=note midinote=([\d.]+) dur=([\d.]+) "
    r"stretch=([\d.]+) ctranspose=([-\d.]+) detune=([-\d.]+)"
)
_RE_REST = re.compile(
    r"BP2SC_EVENT (\d+): type=rest dur=([\d.]+) stretch=([\d.]+)"
)


def _parse_trace_output(output: str) -> list[TraceEvent]:
    """Parse sclang trace output into TraceEvent objects."""
    events = []
    for line in output.split("\n"):
        m = _RE_NOTE.search(line)
        if m:
            events.append(TraceEvent(
                index=int(m.group(1)),
                type="note",
                midinote=float(m.group(2)),
                dur=float(m.group(3)),
                stretch=float(m.group(4)),
                ctranspose=float(m.group(5)),
                detune=float(m.group(6)),
            ))
            continue

        m = _RE_REST.search(line)
        if m:
            events.append(TraceEvent(
                index=int(m.group(1)),
                type="rest",
                dur=float(m.group(2)),
                stretch=float(m.group(3)),
            ))
            continue

    return events
