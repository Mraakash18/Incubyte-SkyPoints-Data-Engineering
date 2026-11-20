# Engineering decisions and tradeoffs

| Decision | Why | Alternative / limitation |
|---|---|---|
| Source-specific adapters | Different headers, formats, optional fields | Config-driven mapping framework for more sources |
| Preserve raw records | Replay, lineage, debugging, audit | Storage cost; retention rules needed |
| Validate before country routing | Prevent corrupt targets | Keep quarantine available for correction/replay |
| Stable member ID instead of member name | Names are not unique or immutable | Source contract incorrectly marks name as key; confirm |
| Namespace country-local IDs | `ID=1` appears for three different people | Verified global identity crosswalk needed to merge |
| Feed date as latest-wins proxy | No member update timestamp in samples | Same-day updates cannot be ordered; quarantine conflicts |
| Canonical member table | Single source of truth for current country | Country targets are denormalized copies |
| Atomic delete-old/upsert-new | Prevent member existing in two countries | Requires transaction and idempotent retry |
| Null DOB -> null age | DOB is optional in specification | No invented age |
| Null last flight -> unknown stale | Unknown is not equal to >90 days | Business may define different policy |
| Explicit as-of date | Deterministic tests and reproducible output | Refresh flags daily in production |
| Reject ambiguous compact dates | Avoid silent corruption | Confirm date-format contract with source owner |
| Global flat DOB uses DDMMYYYY | Sample has no unambiguous evidence | **Unverified assumption; change after contract confirmation** |
| `PHIL` -> `PHL`, `AU` -> `AUS` | Normalize to ISO alpha-3 codes | Registry should be maintained and versioned |
| `(member, partner, txn_id)` redemption key | Avoid duplicate event replays | Verify partner transaction-ID scope with provider |
| SQLite for local demo | Runs without cloud credentials | Cannot support billions/day; Snowflake design separate |
| Physical country tables | Explicit assessment requirement | Country-filtered secure views often simpler at scale |

## Questions for the source/product owner

1. Is `Member_ID` globally unique across all country feeds? What is the crosswalk for `ID` and `Unique ID`?
2. Is there a member `updated_at`, source sequence number, or CDC operation type? How do we order same-day changes?
3. What is the exact format of `DOB=03051985`? Does the source use DDMMYYYY or MMDDYYYY?
4. For USA compact dates like `1052022`, is there a fixed padding rule?
5. Does `Post Code` exist? The sample header omits it although the spec lists it.
6. Are missing country, DOB, and last-flight values allowed? What should `stale_member` be for never-flown members?
7. What do `A` and `I` mean for `Is_Active`? Is `Individual or Corporate` a separate business field? (Assumed yes.)
8. Can the same redemption transaction ID appear under multiple partners or members?
9. What are the expected file SLA, size, encryption, late-delivery, replay, and schema-change policies?
10. Are physical country tables required for data residency, or would country-secured views suffice?
