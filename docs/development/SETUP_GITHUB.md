# Publishing the Bootstrap to GitHub (Windows / PowerShell)

The connected GitHub integration has repository read access but rejected code and issue writes with HTTP 403. The scaffold is therefore supplied as a ZIP archive. These commands publish it using your own GitHub CLI authentication.

1. Install Git and GitHub CLI.
2. Extract the bootstrap ZIP to a folder.
3. Open PowerShell in that extracted folder.
4. Authenticate and publish the initial commit:

```powershell
gh auth login
git init -b main
git remote add origin https://github.com/aymanfali/ask-ai.git
git add .
git commit -m "chore: bootstrap Ask AI foundation"
git push -u origin main
```

If Git reports that `origin` already exists, inspect it with `git remote -v` before changing it. Do not force-push. The remote repository was empty at the time this bootstrap was prepared.

## Lockfiles

This environment could not reach GitHub/PyPI to resolve dependencies or download Python 3.14. The ZIP intentionally does not include `uv.lock` or `frontend/package-lock.json`. On a connected development machine, run:

```powershell
# Backend
Set-Location backend
uv lock
uv sync --all-groups
Set-Location ..

# Frontend
Set-Location frontend
npm install
npm run typecheck
npm run build
Set-Location ..

# Commit both generated lockfiles
git add backend/uv.lock frontend/package-lock.json
git commit -m "build: lock backend and frontend dependencies"
git push
```

After lockfiles are committed, update CI to use locked installs (`uv sync --locked --all-groups` and `npm ci`).
