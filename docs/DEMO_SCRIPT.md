# Five-minute live demo script

## 0. Before screen sharing

Open a terminal at the project root. Ensure Python is installed. Delete the old `output/skypoints.db` so the demo starts clean.

## 1. Explain architecture (30 seconds)

> I separated raw ingestion from validation and current-member storage. Each source has its own parser because the input formats differ. Valid records go to staging, and the latest verified member state is routed to one country table. Invalid records are quarantined. Redemptions are flattened separately and joined using a verified global member key.

## 2. Run baseline (60 seconds)

```bash
python -m skypoints.cli --db output/skypoints.db --as-of 2026-11-20
```

Explain: 14 raw member rows; 12 accepted; 2 quarantined; 2 redemptions; country counts IND 4, USA 3, AUS 3, PHL 1, CAN 1.

Run `python -m skypoints.inspect --db output/skypoints.db` to show current members, rejected rows, the JSON join and the country move check.

Show the quarantines: invalid Australian enrollment `2021-13-13`, ambiguous USA date `1052022`.

## 3. Show global identity protection (45 seconds)

Open SQLite and query:

```sql
SELECT member_key,member_name,country_code
FROM current_members WHERE source_member_id='1';
```

Explain that country-local `1` is Mike in Australia, Sam in USA and Vikas in India; they are not automatically the same member.

## 4. Demonstrate country move (60 seconds)

```bash
python -m skypoints.cli --db output/skypoints.db --as-of 2026-11-20 --move-demo
```

The synthetic second-day feed moves `GLOBAL:223457` Elena from USA to India. Show she is absent from `country_usa` and present in `country_india`. Emphasize that the move is atomic and newer feed date wins. This additional move feed was created for demonstration, not supplied by Incubyte.

## 5. Demonstrate JSON join (30 seconds)

Show `RX10091` and `RX10092` linked to Elena. Explain that PENDING is stored but should not be counted as completed redeemed miles.

## 6. Run tests (30 seconds)

```bash
python -m pytest -q
```

Expected: 14 passing tests.

## 7. Scale and tradeoffs (45 seconds)

> SQLite is only my local demo. For billions of records, I would land immutable files in object storage, use Snowflake COPY or Spark for parallel ingestion, standardize into staging, deduplicate using source update timestamps, and incrementally MERGE into canonical state. I would also monitor quarantine rates, source-target reconciliation, and costs.

## Likely follow-up questions

- **Why not use member name as key?** Names can duplicate and change; require stable member ID.
- **Why can't you merge `ID=1` across countries?** Those are local IDs for different people; need verified crosswalk.
- **How do you identify the latest record?** Ideally `updated_at`/version; feed date is a documented fallback.
- **Why quarantine USA John?** `1052022` can be interpreted in two valid ways.
- **Why keep PENDING redemptions?** Audit/status tracking, but completed-miles metrics must filter status.
- **How do you recover from failure?** Raw files are retained; upserts are idempotent; country move uses a transaction.
- **Can this process billions/day?** Not locally; the proposed Snowflake design can be evaluated and benchmarked at scale.
