from __future__ import annotations

"""ICS_Forge — generate & validate RFC 5545 iCalendar (.ics) files, zero deps."""

import argparse
import datetime as _dt
import json
import os
import sys
import uuid

# Explicit description string (not __doc__) so it works on macOS Python 3.9.
_DESCRIPTION = (
    "ICS_Forge — generate and validate RFC 5545 iCalendar (.ics) files "
    "from scratch. Zero dependencies, pure Python standard library."
)

# RFC 5545 requires a PRODID identifying the generator.
_PRODUCT_ID = "-//realMNohgee//ICS_Forge 1.0//EN"
# RFC 5545 §3.1: content lines SHOULD NOT be longer than 75 octets.
_FOLD_LIMIT = 75


# ---------------------------------------------------------------------------
# RFC 5545 building blocks
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    """Return the current UTC timestamp in iCalendar form (YYYYMMDDTHHMMSSZ)."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape_text(value: str) -> str:
    """Escape a TEXT value per RFC 5545.

    Backslash, semicolon, comma, and newlines are the four characters that
    must be escaped. Backslashes are escaped FIRST so the later replacements
    don't double-escape them.
    """
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str, limit: int = _FOLD_LIMIT) -> str:
    """Fold a logical line to at most `limit` octets, joining with CRLF+space.

    RFC 5545 §3.1: lines longer than 75 octets are folded by inserting a CRLF
    followed by a single space. We fold on UTF-8 octet boundaries so a
    multi-byte character is never split in half.
    """
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return line
    parts = []
    remaining = raw
    while len(remaining) > limit:
        n = limit
        # Back off to the previous whole UTF-8 character boundary.
        while n > 0:
            try:
                remaining[:n].decode("utf-8")
                break
            except UnicodeDecodeError:
                n -= 1
        parts.append(remaining[:n].decode("utf-8"))
        remaining = remaining[n:]
    parts.append(remaining.decode("utf-8"))
    return "\r\n ".join(parts)


def _build_calendar(title: str, start: _dt.datetime, end: _dt.datetime,
                    desc, location, tzid, uid: str) -> str:
    """Assemble the full .ics text for a single VEVENT.

    With --tzid the event times are emitted as floating local time with a
    TZID parameter; without it they are emitted as UTC (trailing Z).
    """
    if tzid:
        dtstart = "DTSTART;TZID={}:{}".format(tzid, start.strftime("%Y%m%dT%H%M%S"))
        dtend = "DTEND;TZID={}:{}".format(tzid, end.strftime("%Y%m%dT%H%M%S"))
    else:
        dtstart = "DTSTART:{}Z".format(start.strftime("%Y%m%dT%H%M%S"))
        dtend = "DTEND:{}Z".format(end.strftime("%Y%m%dT%H%M%S"))

    logical = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + _PRODUCT_ID,
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        "UID:" + _escape_text(uid),
        "DTSTAMP:" + _now_utc(),
        dtstart,
        dtend,
        "SUMMARY:" + _escape_text(title),
    ]
    # Optional fields are appended only when the user supplied them.
    if desc is not None:
        logical.append("DESCRIPTION:" + _escape_text(desc))
    if location is not None:
        logical.append("LOCATION:" + _escape_text(location))
    logical += ["END:VEVENT", "END:VCALENDAR"]

    # Fold every line to <=75 octets, then join with CRLF line endings.
    return "\r\n".join(_fold(ln) for ln in logical) + "\r\n"


# ---------------------------------------------------------------------------
# CLI input helpers
# ---------------------------------------------------------------------------

def _parse_datetime_arg(value: str, flag: str) -> _dt.datetime:
    """Parse a CLI --start/--end value into a naive datetime.

    Accepts ISO 8601 forms like 2026-08-20T09:00:00 (seconds optional) and a
    space separator in place of 'T'.
    """
    formats = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )
    for fmt in formats:
        try:
            return _dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(
        "invalid {} datetime {!r}: expected ISO 8601 like 2026-08-20T09:00:00".format(flag, value)
    )


def _check_tzid(tzid: str) -> str:
    """Validate a timezone ID against the system IANA database.

    Returns 'ok', 'unknown' (ID not found), or 'unavailable' (no tzdata).
    """
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:  # pragma: no cover - only on Python < 3.9
        return "unavailable"
    try:
        ZoneInfo(tzid)
        return "ok"
    except ZoneInfoNotFoundError:
        # Distinguish a bad tzid from a machine with no tzdata at all.
        try:
            ZoneInfo("UTC")
        except ZoneInfoNotFoundError:
            return "unavailable"
        return "unknown"
    except Exception:
        return "unavailable"


def _read_file(path: str) -> str:
    """Read a file as UTF-8 text (raising FileNotFoundError if missing)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _write_output(path: str, content: str) -> None:
    """Write content to `path`, creating missing parent directories first."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# Line-based ICS parser (BEGIN/END blocks + KEY:VALUE pairs)
# ---------------------------------------------------------------------------

def _unfold_lines(text: str):
    """Return logical lines, rejoining RFC 5545 folded (continuation) lines.

    Normalizes CRLF/CR to LF, strips a UTF-8 BOM, and treats a line starting
    with a space or tab as a continuation of the previous line.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    logical = []
    for line in text.split("\n"):
        if line.startswith((" ", "\t")):
            # Continuation: drop exactly one leading whitespace char.
            if logical:
                logical[-1] += line[1:]
            else:
                logical.append(line)
        else:
            logical.append(line)
    return logical


def _split_property(line: str):
    """Split a content line into (name, params, value), or (None, None, None).

    Handles NAME;PARAM=VALUE:VALUE forms (e.g. DTSTART;TZID=America/Chicago:...).
    """
    if ":" not in line:
        return None, None, None
    left, value = line.split(":", 1)
    if ";" in left:
        name, params_raw = left.split(";", 1)
        params = {}
        for chunk in params_raw.split(";"):
            if "=" in chunk:
                key, val = chunk.split("=", 1)
                params[key.upper()] = val.strip('"')
    else:
        name = left
        params = {}
    return name.upper(), params, value


def _parse_ics_datetime(value: str) -> bool:
    """Return True if an iCalendar DATE-TIME/DATE value is parseable.

    Handles the trailing Z (UTC) suffix, floating local times, and bare dates.
    """
    v = value.strip()
    if not v:
        return False
    # Bare date: YYYYMMDD
    if len(v) == 8 and v.isdigit():
        try:
            _dt.datetime.strptime(v, "%Y%m%d")
            return True
        except ValueError:
            return False
    if v.endswith("Z"):
        v = v[:-1]
    try:
        _dt.datetime.strptime(v, "%Y%m%dT%H%M%S")
        return True
    except ValueError:
        return False


def _parse_ics(text: str):
    """Parse ICS text into (events, violations).

    events: list of dicts, each with 'index' (1-based) and 'props'
            (ordered (name, params, value) tuples).
    violations: list of {"severity", "message"} structural problems.
    """
    lines = _unfold_lines(text)
    events = []
    violations = []
    stack = []            # tracks open BEGIN blocks for balance checking
    current = None        # the VEVENT dict currently being populated
    saw_vcalendar = False
    saw_version = False

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            block = line.split(":", 1)[1].strip().upper()
            stack.append(block)
            if block == "VCALENDAR":
                saw_vcalendar = True
            elif block == "VEVENT":
                current = {"index": len(events) + 1, "props": []}
                events.append(current)
        elif upper.startswith("END:"):
            block = line.split(":", 1)[1].strip().upper()
            if not stack:
                violations.append({"severity": "error",
                                   "message": "line {}: END:{} without matching BEGIN".format(idx, block)})
            else:
                top = stack.pop()
                if top != block:
                    violations.append({"severity": "error",
                                       "message": "line {}: END:{} does not match BEGIN:{}".format(idx, block, top)})
                if block == "VEVENT":
                    current = None
        else:
            name, params, value = _split_property(line)
            if name is None:
                violations.append({"severity": "error",
                                   "message": "line {}: malformed content line (no ':')".format(idx)})
                continue
            if name == "VERSION":
                saw_version = True
                if value.strip() != "2.0":
                    violations.append({"severity": "error",
                                       "message": "line {}: VERSION is {!r}, expected 2.0".format(idx, value.strip())})
            if current is not None:
                current["props"].append((name, params, value))

    if stack:
        violations.append({"severity": "error",
                           "message": "unclosed block(s): {}".format(", ".join(stack))})
    if not saw_vcalendar:
        violations.append({"severity": "error", "message": "missing BEGIN:VCALENDAR"})
    if not saw_version:
        violations.append({"severity": "error", "message": "missing VERSION:2.0"})
    return events, violations


def _prop(event, name: str):
    """Return (params, value) of the LAST occurrence of `name` in an event."""
    found = None
    for n, p, v in event["props"]:
        if n == name:
            found = (p, v)
    return found if found is not None else (None, None)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_create(args) -> int:
    """Generate an .ics file for a single event."""
    # Parse the required start/end datetimes, surfacing a clear error.
    try:
        start = _parse_datetime_arg(args.start, "--start")
        end = _parse_datetime_arg(args.end, "--end")
    except ValueError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1

    # Validate the timezone up front to catch typos early.
    if args.tzid:
        status = _check_tzid(args.tzid)
        if status == "unknown":
            print("Error: unknown timezone: {!r}".format(args.tzid), file=sys.stderr)
            return 1
        if status == "unavailable":
            print("Warning: could not verify timezone {!r} (tzdata unavailable)".format(args.tzid),
                  file=sys.stderr)

    # Warn (but don't fail) on a non-positive duration.
    if end <= start:
        print("Warning: end ({}) is not after start ({})".format(args.end, args.start),
              file=sys.stderr)

    uid = args.uid or str(uuid.uuid4())
    content = _build_calendar(args.title, start, end, args.desc,
                              args.location, args.tzid, uid)

    if args.output:
        # Writing to a file: emit a summary on stdout in the requested format.
        try:
            _write_output(args.output, content)
        except OSError as exc:
            print("Error: cannot write {}: {}".format(args.output, exc), file=sys.stderr)
            return 1
        summary = {
            "output": args.output,
            "uid": uid,
            "bytes": len(content.encode("utf-8")),
            "start": args.start,
            "end": args.end,
        }
        if args.format == "json":
            print(json.dumps(summary, indent=2))
        else:
            print("Wrote {} ({} bytes, UID {})".format(args.output, summary["bytes"], uid))
    else:
        # No --output: the raw .ics goes to stdout; notice goes to stderr so
        # stdout stays clean for shell redirection.
        sys.stdout.write(content)
        print("ICS_Forge: wrote 1 event (UID {}) to stdout".format(uid), file=sys.stderr)
    return 0


def cmd_validate(args) -> int:
    """Validate an .ics file and report a list of violations."""
    try:
        text = _read_file(args.file)
    except FileNotFoundError:
        print("Error: file not found: {}".format(args.file), file=sys.stderr)
        return 1
    except OSError as exc:
        print("Error: cannot read {}: {}".format(args.file, exc), file=sys.stderr)
        return 1

    events, violations = _parse_ics(text)

    # Per-event required-field and date checks.
    for ev in events:
        label = "event {}".format(ev["index"])
        _, uid_val = _prop(ev, "UID")
        if not uid_val or not uid_val.strip():
            violations.append({"severity": "error", "message": "{}: missing UID".format(label)})
        _, dtstart_val = _prop(ev, "DTSTART")
        if not dtstart_val or not dtstart_val.strip():
            violations.append({"severity": "error", "message": "{}: missing DTSTART".format(label)})
        elif not _parse_ics_datetime(dtstart_val):
            violations.append({"severity": "error",
                               "message": "{}: DTSTART is not a parseable date: {!r}".format(label, dtstart_val)})
        _, summary_val = _prop(ev, "SUMMARY")
        if not summary_val or not summary_val.strip():
            violations.append({"severity": "error", "message": "{}: missing SUMMARY".format(label)})
        # DTEND is optional, but when present it must parse as a date.
        _, dtend_val = _prop(ev, "DTEND")
        if dtend_val is not None and dtend_val.strip() and not _parse_ics_datetime(dtend_val):
            violations.append({"severity": "error",
                               "message": "{}: DTEND is not a parseable date: {!r}".format(label, dtend_val)})

    errors = [v for v in violations if v["severity"] == "error"]
    warnings = [v for v in violations if v["severity"] == "warning"]

    result = {
        "file": args.file,
        "valid": not errors,
        "events": len(events),
        "errors": [v["message"] for v in errors],
        "warnings": [v["message"] for v in warnings],
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("File:    {}".format(args.file))
        print("Events:  {}".format(len(events)))
        for v in errors:
            print("ERROR:   {}".format(v["message"]))
        for v in warnings:
            print("WARNING: {}".format(v["message"]))
        print("Result:  {} ({} error(s), {} warning(s))".format(
            "VALID" if not errors else "INVALID", len(errors), len(warnings)))
    return 1 if errors else 0


def cmd_list(args) -> int:
    """List every VEVENT's UID, SUMMARY, DTSTART, and DTEND."""
    try:
        text = _read_file(args.file)
    except FileNotFoundError:
        print("Error: file not found: {}".format(args.file), file=sys.stderr)
        return 1
    except OSError as exc:
        print("Error: cannot read {}: {}".format(args.file, exc), file=sys.stderr)
        return 1

    events, violations = _parse_ics(text)
    errors = [v for v in violations if v["severity"] == "error"]

    def _with_tz(val, params):
        """Annotate a datetime value with its TZID when one is present."""
        tz = params.get("TZID") if params else None
        return val if not tz else "{} (TZID={})".format(val, tz)

    out_events = []
    for ev in events:
        _, uid = _prop(ev, "UID")
        _, summary = _prop(ev, "SUMMARY")
        dtstart_params, dtstart = _prop(ev, "DTSTART")
        dtend_params, dtend = _prop(ev, "DTEND")
        out_events.append({
            "uid": uid or "",
            "summary": summary or "",
            "dtstart": _with_tz(dtstart or "", dtstart_params),
            "dtend": _with_tz(dtend, dtend_params) if dtend is not None else "",
        })

    if args.format == "json":
        print(json.dumps({"file": args.file, "events": out_events}, indent=2))
    else:
        if not out_events:
            print("No VEVENTs found in {}".format(args.file))
        for i, ev in enumerate(out_events):
            if i:
                print()
            print("Event {}".format(i + 1))
            print("  UID:     {}".format(ev["uid"]))
            print("  SUMMARY: {}".format(ev["summary"]))
            print("  DTSTART: {}".format(ev["dtstart"]))
            print("  DTEND:   {}".format(ev["dtend"] or "(none)"))

    # A structurally malformed file still fails even if events were listed.
    if errors:
        for v in errors:
            print("ERROR: {}".format(v["message"]), file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Argument parsing + entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with a shared --format parent parser.

    --format is defined on a shared parent with default=argparse.SUPPRESS and
    attached to BOTH the top-level parser and every subparser, so it works
    before AND after the subcommand. The fallback is resolved in main().
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["text", "json"],
                        default=argparse.SUPPRESS,
                        help="Output format: text or json (default: text)")

    p = argparse.ArgumentParser(description=_DESCRIPTION, parents=[common])
    sub = p.add_subparsers(dest="command", required=True)

    # `create` — generate a new .ics file.
    sp_create = sub.add_parser("create", parents=[common],
                               help="Generate a new .ics file for a single event")
    sp_create.add_argument("--title", required=True, help="Event title (SUMMARY)")
    sp_create.add_argument("--start", required=True,
                           help="Start time, ISO 8601 (e.g. 2026-08-20T09:00:00)")
    sp_create.add_argument("--end", required=True,
                           help="End time, ISO 8601 (e.g. 2026-08-20T10:00:00)")
    sp_create.add_argument("--desc", default=None, help="Optional description (DESCRIPTION)")
    sp_create.add_argument("--location", default=None, help="Optional location (LOCATION)")
    sp_create.add_argument("--tzid", default=None,
                           help="IANA timezone ID (e.g. America/Chicago). Emits "
                                "DTSTART;TZID=... as floating local time; without it "
                                "the time is emitted as UTC (trailing Z).")
    sp_create.add_argument("--uid", default=None, help="Optional UID (defaults to a UUID4)")
    sp_create.add_argument("--output", "-o", default=None,
                           help="Write to FILE instead of stdout")
    sp_create.set_defaults(func=cmd_create)

    # `validate` — check an existing .ics file.
    sp_validate = sub.add_parser("validate", parents=[common],
                                 help="Validate an .ics file and report violations")
    sp_validate.add_argument("file", help="Path to the .ics file")
    sp_validate.set_defaults(func=cmd_validate)

    # `list` — show every event's key fields.
    sp_list = sub.add_parser("list", parents=[common],
                             help="List every VEVENT's UID, SUMMARY, DTSTART, DTEND")
    sp_list.add_argument("file", help="Path to the .ics file")
    sp_list.set_defaults(func=cmd_list)

    return p


def main(argv=None) -> int:
    """Entry point: parse args once, resolve the --format fallback, dispatch."""
    args = build_parser().parse_args(argv)
    # SUPPRESS means the attribute only exists when the flag was given; default
    # to "text" when it never appeared.
    args.format = getattr(args, "format", None) or "text"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
