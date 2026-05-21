"""PyInstaller entry script for the Cloudsmith CLI binary.

Kept deliberately minimal: PyInstaller analyses this file as the entry point
and freezes only what the CLI actually needs. Anything more complex belongs in
the package itself.
"""

from cloudsmith_cli.cli.commands.main import main

if __name__ == "__main__":
    # `main` is a click command; click injects ctx/opts/version at runtime.
    main()  # pylint: disable=no-value-for-parameter
