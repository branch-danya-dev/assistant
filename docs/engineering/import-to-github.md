# Import package into the empty GitHub repository

GitHub target: `dev-danrogulin/assistant` (currently public and empty as inspected 2026-10-29). The connected account used during preparation was `branch-danya-dev` with `push=false`; therefore these files were **not** written to GitHub. Import using an account with write access.

1. Download/extract the supplied `assistant-foundation.zip` into a temporary directory.
2. Open PowerShell in that directory and run the commands below (or copy files into an already authenticated clone):

```powershell
git init
git branch -M main
git add .
git commit -m "docs: initialize agent-first assistant project foundation"
git remote add origin https://github.com/dev-danrogulin/assistant.git
git push -u origin main
```

Before pushing, verify `git remote -v`, current account credentials and that the target repository is still empty. If it is no longer empty, **clone and merge manually** instead of force-pushing. Nothing in this package includes live credentials or user data.

After import check GitHub Actions `Spec validation` and confirm the default branch. If the linked GitHub app needs future direct write access, install/authorize it for the correct repository and grant content-write permission.
