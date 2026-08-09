# aisel — a metrics pipeline that refuses to guess

[![collect](https://github.com/xieyi138-star/ai-selection-site/actions/workflows/collect.yml/badge.svg)](https://github.com/xieyi138-star/ai-selection-site/actions/workflows/collect.yml)

Every day, this collects 18 hard metrics for 40 open-source AI infrastructure
projects from four independent sources, and commits the snapshot back to the
repository. It is the data layer for judging which project a developer should
actually pick at each stage of an AI stack.

The design rule that shaped every line of it:

> **If a value cannot be measured, the run fails. It never returns a
> plausible-looking default.**

That rule exists because of what happened when it was missing — see
[What it caught](#what-it-caught).

---

## Status

| Layer | State |
|---|---|
| Collection (sources, retry, storage, CI) | **Built, tested, running daily** |
| Scoring / verdicts / rendered pages | Specified, not built |

The scoring design is written up in [the spec](docs/superpowers/specs/2026-08-09-github-ai-selection-site-design.md)
and [the plan](docs/superpowers/plans/2026-08-09-p0-p1-data-and-verdict.md);
[`scripts/preview_verdicts.py`](scripts/preview_verdicts.py) is a throwaway
preview used to falsify the threshold design early, not the product.

Evidence for "running daily", so you don't have to take my word for it:
the [Actions tab](https://github.com/xieyi138-star/ai-selection-site/actions)
shows real runs, and `data/aisel.db` carries commits authored by `aisel-bot`.

---

## What it collects

**40 repositories across 5 stages** — `agent-orchestration`, `rag`,
`vector-db`, `inference`, `observability`. The roster in
[`config/repos.yaml`](config/repos.yaml) documents, inline, why each project is
on the list and why several better-known ones are not.

**18 metrics per repo per day**, in long format
(`repo_id, date, metric, value`), from four sources:

| Source | Signal |
|---|---|
| GitHub REST | stars, forks, commits (90d), contributors (90d), days since last release |
| GitHub GraphQL | issues opened/closed (90d), first-response median latency, issues with no response |
| pypistats.org | PyPI downloads, 30d and prior 30d (mirror traffic excluded) |
| npm registry | npm downloads, 30d and prior 30d |
| Docker Hub | cumulative image pulls |

Prior-period counterparts are collected alongside current-period ones so growth
can be computed without a second pass, and the actual **number of days
observed** is stored next to each download figure — a 30-day window that only
returned 23 days of data must not be silently compared against a full one.

---

## What it caught

The interesting output of this project is not the numbers. It is the four
defects found *before* the data was used, each of which produced a green log
and a completely reasonable-looking wrong answer.

| # | Symptom | Reality | Fix |
|---|---|---|---|
| 1 | Pagination capped at 3 pages × 100 | 1773 issues collected as 300; three of four repos truncated by ~80%, and the surviving records skewed toward the newest (least-resolved) ones | Fetch the true total first, compare, fail on mismatch |
| 2 | Commit count read from the `Link` header; parse failure fell back to the body length | With `per_page=1` that fallback is always `1`, so a repo with **208 commits in the window** was recorded as **1** — a number nobody would look at twice | Parse failures raise; no defaults |
| 3 | Spot-checked 7 records, all under 5h, against a reported median of 23.6h | The 23.6h was correct. The spot-check was biased — recent, already-answered issues are structurally faster. Deciles: 0.5 / 3.8 / 7.6 / 13.5 / **23.6** / 30.8 / 57.5 / 112.4 / 227.4 | Verify against the distribution, never a handful of rows |
| 4 | Quantile thresholds (top 25% strong, bottom 25% weak) | Forces 25% of any roster into "weak" *by construction* — 17 of 40 projects, including several industry defaults, came out as "avoid" | Absolute thresholds with real-world meaning ("no release in a year"), which dropped false "avoid" verdicts from 17 to 4 |

Three more, found in review rather than in production:

- **Transport errors got 1 attempt while HTTP 503 got 4.** The single most
  common transient failure was the only one not covered by the retry loop.
- **One shared `httpx.Client` would have sent the GitHub bearer token to
  pypistats, npm and Docker Hub** on every daily run. Split into two clients,
  with `follow_redirects=False` set explicitly on both so the isolation does
  not depend on a library default.
- **A single repo failing would have discarded all 40 repos' data for the day.**
  The commit step now runs `if: always()` — keep the data, let the run go red.

---

## Design notes worth reading

- **[`CONSTITUTION.md`](CONSTITUTION.md)** — three rules that stay locked
  precisely because breaking them would improve a short-term number. The test
  for whether a rule belongs there: *would violating it make revenue go up?*
- **Bands as filter, magnitude as order.** Rating into strong/moderate/weak
  discards magnitude, so bands decide inclusion and raw numbers decide order.
- **Asymmetric combination.** "Alive" and "responsive" combine sub-signals with
  `worst()` — they describe failure modes, and one broken sub-signal is enough.
  "Adoption" combines with `best()` — it is evidence of use, and publishing on
  one channel is not weakened by absence from another.
- **`unknown` is a real answer.** A project publishing only through a channel
  with too few samples to calibrate scores `unknown`, not a borrowed band from
  incomparable units.
- **A known epistemic limit, stated rather than hidden:** package-manager
  download counts include CI traffic. 316M installs is not 316M people. The
  metric is kept because it is the best available usage signal, and the
  limitation is published with it.

---

## Run it

Requires Python 3.12.

```bash
pip install -e ".[dev]"
pytest -q                                   # 38 tests
GITHUB_TOKEN=$(gh auth token) python -m aisel.pipeline --config config/repos.yaml
```

A full collection run takes roughly 12–15 minutes; the most recent CI run
measured 14m33s. Output goes to `data/aisel.db` (`AISEL_DB_URL` overrides the
location). SQLite is the default. No SQLite-specific SQL appears in query code
— the single exception is a dialect-gated `PRAGMA foreign_keys=ON` at connect
time, because pysqlite leaves foreign keys off while Postgres has them on, and
that divergence would let SQLite accept orphan rows Postgres would reject. The
storage layer moves to Postgres by changing the URL.

CI runs daily at 03:17 UTC and can be triggered manually from the Actions tab.

---

## Stack

Python 3.12 · SQLAlchemy 2.x · httpx · PyYAML · pytest + respx · GitHub Actions

---

## 中文说明

这是一条每天自动运行的数据采集管道：40 个开源 AI 基础设施项目、4 类外部数据源、
18 个指标，跑完把快照提交回仓库。

贯穿全项目的一条规矩：**测不到就报错，绝不返回一个看起来合理的默认值。**

它的价值不在采到的数字，而在上线前抓出的四个缺陷——四个的共同点都是
**程序不报错、日志全绿、数字看着完全正常，但它是错的**。详见上文
[What it caught](#what-it-caught)。

当前状态：采集层（数据源、重试、存储、CI）已完成并每天在跑；评级与页面渲染层
已设计未实现。
