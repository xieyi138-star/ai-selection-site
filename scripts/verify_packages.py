"""Prove every declared package name resolves. A typo here is invisible to the
test suite (collectors are mocked) and silently zeroes a repo's adoption axis."""
from __future__ import annotations

import argparse

import httpx

from aisel.config import load_repos

ENDPOINTS = {
    "pypi": "https://pypi.org/pypi/{}/json",
    "npm": "https://registry.npmjs.org/{}",
    "dockerhub": "https://hub.docker.com/v2/repositories/{}/",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/repos.yaml")
    args = parser.parse_args()

    bad: list[str] = []
    signalless: list[str] = []

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for spec in load_repos(args.config):
            slug = f"{spec.owner}/{spec.name}"
            declared = {
                "pypi": spec.pypi_package,
                "npm": spec.npm_package,
                "dockerhub": spec.dockerhub_repo,
            }
            if not any(declared.values()):
                signalless.append(slug)
                continue
            for kind, value in declared.items():
                if not value:
                    continue
                url = ENDPOINTS[kind].format(value)
                resp = client.get(url)
                if resp.status_code != 200:
                    bad.append(f"{slug}  {kind}={value}  HTTP {resp.status_code}  {url}")

    for slug in signalless:
        print(f"NO-PACKAGE  {slug}  -> adoption axis will be 'unknown' (allowed, must be deliberate)")
    for line in bad:
        print(f"BAD  {line}")
    print(f"\n{len(bad)} bad, {len(signalless)} without any package")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
