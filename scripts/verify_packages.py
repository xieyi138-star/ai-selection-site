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
    declared_count = {"pypi": 0, "npm": 0, "dockerhub": 0}
    total = 0

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for spec in load_repos(args.config):
            total += 1
            slug = f"{spec.owner}/{spec.name}"
            declared = {
                "pypi": spec.pypi_package,
                "npm": spec.npm_package,
                "dockerhub": spec.dockerhub_repo,
            }
            for kind, value in declared.items():
                if value:
                    declared_count[kind] += 1
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

    # Coverage snapshot. Without this, a download metric that covers only 1 of
    # 40 repos looks like a collector that silently failed, when in fact the
    # collector ran exactly as configured -- it only queries a registry when a
    # package name is declared (see collectors/downloads.py: `if
    # spec.pypi_package:`), and a genuine fetch failure raises rather than
    # skipping. Printing the denominator turns "is this broken?" into a fact
    # you can read off, instead of an investigation.
    print("\nDeclared-package coverage (this is CONFIG, not collector health):")
    for kind in ("pypi", "npm", "dockerhub"):
        n = declared_count[kind]
        print(f"  {kind:<11} {n:>3} / {total} repos declare a name"
              f"  -> only these {n} get downloads_{kind}* rows")
    print("  A low number here means the name was never declared, NOT that the"
          " fetch failed;")
    print("  a failed fetch aborts the run instead of writing nothing.")

    print(f"\n{len(bad)} bad, {len(signalless)} without any package")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
