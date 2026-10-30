# Windows G-drive storage and portability (ADR-016)

**Binding default:** `G:\Assistant`, as defined in `spec/storage-config.json`. This is a documentation/configuration convention; neither the local folders nor Ollama models are installed yet.

## Layout
```text
G:\Assistant\
├── repo\                 # Only Git repository
├── models\ollama\        # Ollama model files
├── data\db\              # SQLite task/event databases
├── data\history\         # Task/conversation history
├── data\memory\          # Semantic/project memory
├── data\identity\        # Persona and preferences
├── data\skills\          # Approved skills
├── workspace\            # Generated working files
├── logs\                 # Local redacted diagnostics
├── backups\              # Local recovery (same disk is not disaster-proof)
└── cache\                # Regenerable cache
```

The code and all internal database references must use paths relative to `ASSISTANT_ROOT`; it defaults to `G:\Assistant` on the owner Windows host. Reject `..` traversal and symlink/reparse-point escapes. Missing G: or insufficient access must fail visibly, **never silently writing on C:**. Explicit temporary overrides are allowed for tests and CI. All state lives outside `repo/`, so model blobs, conversations, databases, artifacts, logs, caches and backups are not versioned in Git.

## Windows first-time setup (manual, after owner authorization)

```powershell
$root = 'G:\Assistant'
if (-not (Test-Path 'G:\')) { throw 'Drive G: is unavailable; abort.' }
$folders = @('repo','models\ollama','data\db','data\history','data\memory','data\identity','data\skills','workspace','logs','backups','cache')
foreach ($dir in $folders) { New-Item -ItemType Directory -Path (Join-Path $root $dir) -Force | Out-Null }
[Environment]::SetEnvironmentVariable('ASSISTANT_ROOT', $root, 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', (Join-Path $root 'models\ollama'), 'User')
```

Fully Quit Ollama Desktop and relaunch after changing user environment. Setting `OLLAMA_MODELS` only in the assistant's `.env` does **not** redirect an independently running Ollama process. Then `ollama pull qwen3.5:9b` and `ollama list` when ready. If models already exist elsewhere, plan/verify migration before removing originals. Reference: https://docs.ollama.com/faq.

## Migration / recovery

1. Stop workers and Ollama; preserve pending approvals and use a consistent SQLite backup (online backup API or controlled offline checkpoint, not naive copy during active writes).
2. Copy the entire directory to the destination with integrity checks. `cache/` is optional, and models can also be re-downloaded. Store at least one **encrypted backup on a different physical disk or external storage**; `G:\Assistant\backups` alone is not protection against G: failure.
3. Change `ASSISTANT_ROOT` and `OLLAMA_MODELS` on the destination, restart Ollama, relocate/re-clone repo, and restore protected credentials separately (e.g., Windows Credential Manager). Ollama executable/OS integrations are not automatically portable.
4. Verify model visibility, SQLite integrity, history, identity, memory, skills, task recovery and permissions. Retain old files until an actual restore succeeds.

Never commit runtime state, model weights or secrets to Git.
