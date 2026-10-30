# GitHub repository checkout and local Windows bootstrap

This repository is **already hosted** at https://github.com/branch-danya-dev/assistant on branch `main`. Historical instructions about an empty `dev-danrogulin/assistant` repository are obsolete. Do not initialize a new Git history, force-push, or import old ZIP packages over this repository.

## Windows setup on the owner computer

1. Verify G: is the intended SSD and `G:\Assistant` is the approved root (`ADR-016`).
2. Follow `docs/architecture/storage.md` to provision `G:\Assistant\repo`, model and data directories (with user approval).
3. Clone the existing GitHub repository **inside** `G:\Assistant\repo`:

```powershell
git clone https://github.com/branch-danya-dev/assistant.git G:\Assistant\repo
cd G:\Assistant\repo
git remote -v
git status
```

4. Install Python 3.12+ and developer dependencies; follow `docs/engineering/implementation.md`.
5. Set the Windows User `OLLAMA_MODELS` variable to `G:\Assistant\models\ollama` **before pulling** `qwen3.5:9b`. Restart Ollama; `.env` does not configure the separately running Ollama process.
6. Work in feature branches and reviewable PRs, preserve the machine-readable specs and run CI before merging.

This is a setup guide, not evidence that any of these commands were executed on the owner's machine.
