#!/usr/bin/env python3
"""Downloads the wheel of each release releases.lock names (`<repo> <tag>` lines) from GitHub; the repositories are
private: GH_TOKEN (read-only) is required. Standard library only (it runs before anything is installed).
Usage: GH_TOKEN=... python3 fetch_wheels.py LOCK OUT_DIR"""
import json
import os
import sys
import urllib.request

OWNER = "Y-Blues"


def get(url, token, accept):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": accept,
                                                   "User-Agent": "planningpoker-build"})
    return urllib.request.urlopen(request, timeout=60)


def main(lock, out):
    token = os.environ["GH_TOKEN"]
    os.makedirs(out, exist_ok=True)
    with open(lock, encoding="utf-8") as file:
        pins = [line.split("#", 1)[0].split() for line in file]
    for repo, tag in (pin for pin in pins if pin):
        with get(f"https://api.github.com/repos/{OWNER}/{repo}/releases/tags/{tag}", token,
                 "application/vnd.github+json") as response:
            assets = [asset for asset in json.load(response)["assets"] if asset["name"].endswith(".whl")]
        if not assets:
            sys.exit(f"{repo}@{tag}: no wheel in the release")
        for asset in assets:
            print(f"{repo}@{tag}: {asset['name']}")
            with get(asset["url"], token, "application/octet-stream") as response, \
                    open(os.path.join(out, asset["name"]), "wb") as target:
                target.write(response.read())


if __name__ == "__main__":
    main(*sys.argv[1:3])
