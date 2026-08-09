"""Preview the verdicts today's real data would produce.

NOT the product. The real scoring layer is Tasks 12-14 and will be reviewed like
everything else. This script exists to answer one question early and cheaply:
does the four-axis judgement, calibrated on real numbers, produce conclusions a
developer would recognise as sensible? Finding out now costs a script; finding
out after P2 costs a site.

Thresholds are calibrated here exactly as the plan specifies:
  higher-is-better -> strong = p75, moderate = p25
  lower-is-better  -> strong = p25, moderate = p75
Sentinels (-1 no sample, 9999 never released) are excluded before quantiles.
"""
from __future__ import annotations

import sqlite3
import statistics
import sys

NO_SAMPLE = -1.0
NEVER_RELEASED = 9999.0
SENTINELS = {NO_SAMPLE, NEVER_RELEASED}
BAND_RANK = {"unknown": 0, "weak": 1, "moderate": 2, "strong": 3}

HIGHER_BETTER = {
    "adoption_pypi": "downloads_pypi_30d",
    "adoption_npm": "downloads_npm_30d",
    "adoption_docker": "dockerhub_pulls_total",
    "alive_commits": "commits_90d",
    "alive_bus": "contributors_90d",
}
LOWER_BETTER = {
    "alive_release": "days_since_last_release",
    "responsive_latency": "issue_first_response_p50_hours",
}


def load(db: str) -> tuple[dict[int, dict[str, float]], dict[int, tuple[str, str]]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    latest = c.execute("select max(date) from metrics_daily").fetchone()[0]
    metrics: dict[int, dict[str, float]] = {}
    for rid, m, v in c.execute(
            "select repo_id, metric, value from metrics_daily where date=?", (latest,)):
        metrics.setdefault(rid, {})[m] = v
    repos = {rid: (f"{o}/{n}", uc) for rid, o, n, uc
             in c.execute("select id, owner, name, use_case_id from repos")}
    print(f"snapshot date: {latest}   repos: {len(metrics)}\n")
    return metrics, repos


def close_ratio(m: dict[str, float]) -> float | None:
    opened = m.get("issues_opened_90d", 0.0)
    return None if opened <= 0 else m.get("issues_closed_90d", 0.0) / opened


def calibrate(metrics) -> dict[str, dict[str, float]]:
    th: dict[str, dict[str, float]] = {}
    for band, metric in {**HIGHER_BETTER, **LOWER_BETTER}.items():
        vals = sorted(m[metric] for m in metrics.values()
                      if metric in m and m[metric] not in SENTINELS)
        if len(vals) < 8:  # too few samples to calibrate a band honestly
            continue
        q = statistics.quantiles(vals, n=4)
        th[band] = ({"strong": q[2], "moderate": q[0]} if band in HIGHER_BETTER
                    else {"strong": q[0], "moderate": q[2]})
    ratios = sorted(r for r in (close_ratio(m) for m in metrics.values()) if r is not None)
    q = statistics.quantiles(ratios, n=4)
    th["responsive_close_ratio"] = {"strong": q[2], "moderate": q[0]}
    return th


def rate(value: float, band: dict[str, float], lower_better: bool) -> str:
    if lower_better:
        return ("strong" if value <= band["strong"]
                else "moderate" if value <= band["moderate"] else "weak")
    return ("strong" if value >= band["strong"]
            else "moderate" if value >= band["moderate"] else "weak")


def combine(bands: list[str], best: bool) -> str:
    present = [b for b in bands if b != "unknown"]
    if not present:
        return "unknown"
    pick = max if best else min
    return pick(present, key=lambda b: BAND_RANK[b])


def axes(m: dict[str, float], th) -> dict[str, str]:
    # A channel with too few samples to calibrate cannot be judged at all.
    # Borrowing another channel's band would be inventing a threshold — the
    # units are not comparable. Repos that publish only through an
    # uncalibratable channel therefore score `unknown`, which is the honest
    # answer rather than a manufactured one.
    adoption = combine([rate(m[metric], th[band], False)
                        for band, metric in HIGHER_BETTER.items()
                        if band.startswith("adoption_") and metric in m
                        and band in th], best=True)
    alive = combine(
        ([rate(m["days_since_last_release"], th["alive_release"], True)]
         if m.get("days_since_last_release", NEVER_RELEASED) != NEVER_RELEASED else [])
        + [rate(m[metric], th[band], False)
           for band, metric in (("alive_commits", "commits_90d"),
                                ("alive_bus", "contributors_90d")) if metric in m],
        best=False)
    resp = []
    lat = m.get("issue_first_response_p50_hours", NO_SAMPLE)
    if lat != NO_SAMPLE:
        resp.append(rate(lat, th["responsive_latency"], True))
    cr = close_ratio(m)
    if cr is not None:
        resp.append(rate(cr, th["responsive_close_ratio"], False))
    return {"adoption": adoption, "alive": alive,
            "responsive": combine(resp, best=False), "runnable": "unknown"}


def confidence(m: dict[str, float], r: dict[str, str]) -> str:
    known = [r["adoption"] != "unknown", r["alive"] != "unknown",
             r["responsive"] != "unknown"]
    if all(known):
        return "high"
    if known[1] and known[2] and m.get("forks_total", 0.0) >= 1000:
        return "medium"
    return "low"


def recommend(rank: int, r: dict[str, str], conf: str) -> str:
    if conf == "low":
        return "insufficient_data"
    if r["alive"] == "weak" or r["responsive"] == "weak":
        return "avoid"
    if rank == 1 and r["runnable"] == "pass" and not any(
            r[a] == "weak" for a in ("adoption", "alive", "responsive")):
        return "primary"
    return "conditional"


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else "aisel.db"
    metrics, repos = load(db)
    th = calibrate(metrics)

    print("calibrated thresholds (from today's 40 repos)")
    for band in sorted(th):
        b = th[band]
        print(f"  {band:24} strong={b['strong']:>16,.2f}  moderate={b['moderate']:>16,.2f}")

    stages: dict[str, list] = {}
    for rid, m in metrics.items():
        slug, stage = repos[rid]
        r = axes(m, th)
        conf = confidence(m, r)
        strong = sum(r[a] == "strong" for a in ("adoption", "alive", "responsive"))
        stages.setdefault(stage, []).append((strong, r, conf, slug))

    for stage in sorted(stages):
        rows = sorted(stages[stage], key=lambda t: (-t[0], -BAND_RANK[t[1]["adoption"]], t[3]))
        print(f"\n=== {stage} ===")
        print(f"  {'repo':34} {'adopt':9} {'alive':9} {'respond':9} {'conf':7} verdict")
        for rank, (_, r, conf, slug) in enumerate(rows, 1):
            print(f"  {slug:34} {r['adoption']:9} {r['alive']:9} {r['responsive']:9} "
                  f"{conf:7} {recommend(rank, r, conf)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
