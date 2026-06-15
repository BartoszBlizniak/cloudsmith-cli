import sys

from cloudsmith_cli.cli.commands.main import main


def _force_utf8_output() -> None:
    """Prevent UnicodeEncodeError on legacy Windows consoles.

    A frozen Windows console defaults to a legacy code page (e.g. cp1252) that
    cannot encode the check/cross/warning UI glyphs the CLI prints; without
    this, commands such as ``mcp configure`` and the download progress output
    crash with UnicodeEncodeError. Reconfiguring the streams to UTF-8 is a
    no-op on POSIX (already UTF-8) and is skipped when a stream cannot be
    reconfigured (e.g. a redirected non-text stream).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    _force_utf8_output()
    main()  # pylint: disable=no-value-for-parameter
