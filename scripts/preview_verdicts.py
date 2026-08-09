"""Preview the verdicts today's real data would produce.

NOT the product. The real scoring layer is Tasks 12-14 and will be reviewed like
everything else. This script exists to answer one question early and cheaply:
does the four-axis judgement, calibrated on real numbers, produce conclusions a
developer would recognise as sensible? Finding out now costs a script; finding
out after P2 costs a site.

It answered that question by failing it. The plan specified quantile-calibrated
thresholds (higher-is-better -> strong = p75, moderate = p25; lower-is-better
the mirror image). Run against the real forty repos, that scheme labelled 17 of
them "avoid" — including pgvector, Chroma, Milvus, FAISS and LlamaIndex —
because ranking in the bottom quartile of a list of good tools is not the same
thing as being bad. See THRESHOLDS below for what replaced it.
"""
from __future__ import annotations

import sqlite3
import sys

NO_SAMPLE = -1.0
NEVER_RELEASED = 9999.0
BAND_RANK = {"unknown": 0, "weak": 1, "moderate": 2, "strong": 3}

HIGHER_BETTER = {
    "adoption_pypi": "downloads_pypi_30d",
    "adoption_npm": "downloads_npm_30d",
    "adoption_docker": "dockerhub_pulls_total",
    "alive_commits": "commits_90d",
    "alive_bus": "contributors_90d",
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


# ABSOLUTE thresholds. Each line answers a question a developer would actually
# ask, and means the same thing whoever else is on the list. Quantiles of the
# roster were tried first and had to be abandoned: they force ~25% of repos into
# "weak" on every axis BY CONSTRUCTION, so a list of forty good tools still
# produces ten "avoid" verdicts. pgvector came out as "avoid" because a mature
# Postgres extension does not commit as often as a hyperactive AI framework —
# that is maturity, not death.
THRESHOLDS: dict[str, dict[str, float]] = {
    # "Has it shipped anything lately?" A year of silence on a tool people
    # depend on is a real signal; a quiet quarter is not.
    "alive_release":  {"strong": 90.0, "moderate": 365.0},
    # "Is anyone still working on it?" Zero commits in a quarter is dormant.
    "alive_commits":  {"strong": 20.0, "moderate": 1.0},
    # "What happens if the maintainer stops?" One contributor is bus factor 1.
    "alive_bus":      {"strong": 5.0, "moderate": 2.0},
    # "If I open an issue, when do I hear back?" A day, a week, or worse.
    "responsive_latency": {"strong": 24.0, "moderate": 168.0},
    # "Do issues actually get resolved?" Busy repos close a smaller share, so
    # this line is deliberately forgiving.
    "responsive_close_ratio": {"strong": 0.40, "moderate": 0.10},
    # Real installs per month. Meaningful on their own scale, per channel.
    "adoption_pypi":   {"strong": 1_000_000.0, "moderate": 50_000.0},
    "adoption_npm":    {"strong": 1_000_000.0, "moderate": 50_000.0},
    # Docker pulls are cumulative since the image existed, so the bar is higher.
    "adoption_docker": {"strong": 10_000_000.0, "moderate": 500_000.0},
}


def calibrate(metrics) -> dict[str, dict[str, float]]:
    """Absolute thresholds; the data is only used to report where they land."""
    return THRESHOLDS


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


AXIS_NAMES = ("adoption", "alive", "responsive")


def recommend(rank: int, r: dict[str, str], conf: str) -> str:
    """`avoid` is a strong word and needs a strong trigger.

    The first version fired it on ANY single weak sub-signal, which labelled
    pgvector, Chroma, Milvus, FAISS and LlamaIndex "do not use". A developer
    reading that would stop trusting the whole page — and they would be right.
    Two independent axes have to be weak before we say it.
    """
    if conf == "low":
        return "insufficient_data"
    weak = sum(r[a] == "weak" for a in AXIS_NAMES)
    if weak >= 2:
        return "avoid"
    if rank == 1 and weak == 0 and r["runnable"] != "fail":
        return "primary"
    return "conditional"


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else "aisel.db"
    metrics, repos = load(db)
    th = calibrate(metrics)

    print("absolute thresholds (fixed lines, NOT derived from this roster)")
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
