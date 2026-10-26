# Copyright 2026 Cloudsmith Ltd
"""The usage telemetry state file, ``telemetry.json`` in the config dir.

Holds the install ID (only when enabled), the shown notice version and the
time of the last failed send. Read and written on the main thread only.
"""

import json
import os

STATE_FILE_NAME = "telemetry.json"


def config_dir():
    from ...cli.config import get_default_config_path

    return get_default_config_path()


def state_path():
    return os.path.join(config_dir(), STATE_FILE_NAME)


def writable():
    """Tell whether the state file could be written, without creating anything.

    Walks up from the config dir to the nearest directory that exists, since
    ``write`` creates the missing levels.
    """
    try:
        path = os.path.abspath(config_dir())
        while not os.path.isdir(path):
            parent = os.path.dirname(path)
            if parent == path:
                return False
            path = parent
        return os.access(path, os.W_OK)
    except OSError:
        return False


def read():
    try:
        with open(state_path(), encoding="utf-8") as state_file:
            data = json.load(state_file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(updates):
    from ..cache_utils import atomic_write_json

    data = read()
    data.update(updates)
    path = state_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        atomic_write_json(path, data)
    except OSError:
        return False
    return True


def delete():
    try:
        os.remove(state_path())
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
