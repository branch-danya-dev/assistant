# M1 file classification alias remediation

Review baseline: PR #6 `d89cb03be69a291ec249e2776de4198f4cce8940`, base
`feat/m1-safe-create-revisions` (`62df23f2e49c6f90134d6d7ad46c7fc284d77696`).
[Independent finding](https://github.com/branch-danya-dev/assistant/pull/6#pullrequestreview-5718611201).
This change starts from that HEAD on a new branch targeting `feat/m1-security-boundaries`.
No existing PR, main, deployed application, production database or OS setting is changed.

## Policy and implementation (ADR-024)

`files=["note.txt", "NOTE.TXT"]` with only `NOTE.TXT` restricted previously allowed
the same Windows object to be read as internal through `note.txt`. The new policy rejects
the entire ambiguous scope, including identical duplicate grants and same-label aliases.
It never chooses the weaker label, deduplicates silently, rewrites a grant, or copies an approval.

| Case | Enforced boundary |
| --- | --- |
| Duplicate paths | Reject duplicate entries in each of files/create_files/private_files. On Windows reject different spellings with the same NFC(casefold) key across those lists. Exact reuse across lists is allowed (e.g. create then read); private grants require the exact private label. Labels and create bindings must use exact listed keys. |
| Windows case aliases | The collision key is conservative rejection, not authorization. Every opened ancestor and target must also have the exact normalized long spelling reported by its handle; drive-letter case alone is ignored. A single `NOTE.TXT` grant for actual `note.txt` is refused, not rebound. |
| 8.3 short names | Reject a short spelling when the handle reports a different long spelling, including directory components before creation. Do not rely on a tilde heuristic or on 8.3 being enabled. A genuine long name containing `~` is not inherently an alias. |
| Unicode | Exact Unicode long names are supported. NFC/casefold collisions fail closed even if the filesystem considers the two names distinct (e.g. composed/decomposed accents or ss/ß). No filename is normalized on disk or in stored policy. Python casefold is **not** claimed equivalent to NTFS upcasing; exact opened names are the additional authority check. |
| Hardlinks / physical identity | Existing regular-file checks require link count exactly one before/after reading and creating. Metadata preflight also rejects linked objects, unavailable identity, and repeated device/inode identity. No inference of privacy from a second pathname. |
| NTFS case-sensitive directories | Query FileCaseSensitiveInfo on every pinned Windows directory handle. Any flag or unsupported/failed query denies access; no fallback to assumed case-insensitivity. No directory flag is changed. Real ordinary-directory tests plus injected positive/failed-query tests exist; a real case-sensitive directory is not claimed tested unless separately recorded. |
| Linux | Exact byte/Unicode spellings remain separate; Windows casefold rules are not imposed. Hardlink/no-follow checks remain. ADR-021 trusted anchors, flat-create, O_TMPFILE/exclusive publication and Landlock ABI 3+ remain binding. |

Windows requires exact long spelling for the complete configured directory chain as well.
An incorrectly cased/short-form root now fails visibly. Non-NTFS or older Windows filesystems
that cannot report directory case policy are unsupported by this backend. This intentionally
narrows accepted paths; it does not establish a new permissive fallback.

## Boundaries and compatibility

1. Journal.create validates scope syntax/collisions, then runs bounded, metadata-only physical
   preflight before saving any task. Restricted content bytes are never read by preflight.
2. Agent.run validates saved scope and preflights before any model call, action preparation,
   approval consumption or tool dispatch. Invalid legacy scope becomes blocked with a closed
   error code. Existing plans/action IDs/approvals/results and raw scope remain unchanged.
3. Registry.resolve revalidates the complete logical scope without blocking filesystem calls.
   Registry execute/observe repeat physical preflight in the bounded worker. The actual
   read/create handles repeat long-name, no-link, parent binding and regular-file checks;
   preflight is not used as a TOCTOU substitute.
4. Saved read results revalidate logical scope at the data boundary. A restricted/private
   grant cannot be weakened by choosing another spelling in a result or model intent.

There are at most 40 read names, 40 create names and 40 private grants. Preflight reads metadata,
not source bytes, and uses the existing worker deadline/cancellation/output bounds. Missing
future names remain exact path grants; no physical binding or alternative name is invented.
Path grants classify subsequent content at that exact name, not an immutable historical inode
or content hash. Hostile same-account relocation/replacement and owner misclassification remain
outside the promised content-classification guarantee. Independent evidence verification and
one-use effect approvals remain unchanged.

SQLite remains v3. No automatic migration or relabelling occurs. To recover a blocked legacy
scope, the owner should inspect names/labels and create a new task with exact long names;
do not edit old approvals, retry uncertain effects or use an older binary as a privacy rollback.
Pending uncertain effects retain needs_reconciliation and require the existing observation
workflow. Production deployment/backup/rollback remains a separate owner action.

## Evidence and remaining acceptance

`tests/test_file_aliases.py` exercises real case aliases, Unicode names, hardlinks, CLI scope,
metadata denial before content reads, legacy scope preservation and worker revalidation.
8.3 tests use GetShortPathNameW and explicitly skip if the fixture has no generated alias.
Directory query fault injection is reported separately from real filesystem evidence.
The unchanged full regression matrix covers the original security, journal, revision,
preview, context, migration and isolated installed-wheel workflows.

See `evidence/m1-alias-validation.json` for exact source, platform counts, skips and CI.
M1 is still in_progress; REQ-017/019 remain specified, P0/M1 with original acceptance.
The proposed [ADR-025 agreement](m1-trust-boundary-proposal.md) is **not accepted**.

Integration only on separate owner commands: **#4 → #5 → #6 → this new PR**. After each
lower integration, separately authorize any next retarget/rebase, preserve commits, rerun
review/CI against the actual HEAD/base, then separately decide merge. No merge is authorized here.

## Platform references

The implementation deliberately rejects ambiguity described in Microsoft's
[filename and short-name rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file),
[per-directory case sensitivity](https://learn.microsoft.com/en-us/windows/wsl/case-sensitivity),
[opaque WCHAR filename semantics](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation),
and [normalized opened-handle paths](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew).
These describe platform behavior, not evidence that every filesystem variant was tested.
