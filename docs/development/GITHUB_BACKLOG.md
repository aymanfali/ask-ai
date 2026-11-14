# GitHub Issue Backlog

Thirteen ordered issue definitions are stored in `github-issues/`. They have not yet been created in GitHub. After this scaffold has been pushed and GitHub CLI is authenticated with an account that has repository write access, run from the repository root:

```bash
python scripts/create_github_issues.py
```

The script submits issues in filename order and stops on the first error. Review the issue files before running it; issue creation mutates the repository.
