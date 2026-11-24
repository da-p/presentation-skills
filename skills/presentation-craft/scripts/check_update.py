#!/usr/bin/env python3
"""Compare the installed presentation skills version with its published version."""

from http.client import HTTPException
import json
from pathlib import Path
import re
from urllib.request import urlopen


VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
VERSION_URL = (
    "https://raw.githubusercontent.com/da-p/presentation-skills/main/"
    "skills/presentation-craft/VERSION"
)


def parse_version(data):
    version = data.strip()
    if not re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Expected MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in version.split(b"."))


def check_update():
    result = {"status": "unavailable"}
    try:
        installed = parse_version(VERSION_FILE.read_bytes())
        result["installed"] = ".".join(map(str, installed))
        with urlopen(VERSION_URL, timeout=3) as response:
            data = response.read(64)
        if len(data) == 64:
            raise ValueError("Version response is too long")
        latest = parse_version(data)
    except (OSError, HTTPException, ValueError):
        return result

    result["latest"] = ".".join(map(str, latest))
    result["status"] = "update_available" if latest > installed else "no_update"
    return result


if __name__ == "__main__":
    print(json.dumps(check_update()))
