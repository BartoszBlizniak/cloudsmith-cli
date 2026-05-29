"""PyInstaller entry point for the Cloudsmith CLI single binary.

Deliberately tiny: PyInstaller analyses this module as the program entry and
freezes what the CLI reaches from `main`. Everything else lives in the package.
"""

from cloudsmith_cli.cli.commands.main import main

if __name__ == "__main__":
    # `main` is a click command; click supplies ctx/opts/version at runtime.
    main()  # pylint: disable=no-value-for-parameter
