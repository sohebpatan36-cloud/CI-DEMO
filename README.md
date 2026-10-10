# Program 8 — Continuous Integration using GitHub Actions

## Aim
Set up a Continuous Integration (CI) pipeline with **GitHub Actions** that
automatically runs a build/test step whenever code is pushed to the `master`
branch, and verify/log the result of the pipeline run.

## The workflow
File: `.github/workflows/deploy.yml`

```yaml
name: CI Workflow

on:
  push:
    branches:
      - master

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Run CI
        run: echo "Build and Test Successful"
```

### What it does
| Item | Value |
|------|-------|
| Workflow name | `CI Workflow` |
| Trigger | `push` to branch `master` |
| Job | `build` |
| Runner | `ubuntu-latest` |
| Step 1 | `Checkout code` — `actions/checkout@v4` |
| Step 2 | `Run CI` — runs `echo "Build and Test Successful"` |

## How it was executed locally
This lab environment has **no `git` and no internet/GitHub access**, so the
push to GitHub and the remote GitHub-hosted runner were **simulated**. To still
produce a genuine pipeline result, the workflow is executed by a small local
**mini CI runner**, `ci_runner.py`, which mimics GitHub Actions:

1. Parses `.github/workflows/deploy.yml` (PyYAML is tried first; if unavailable
   a built-in line-by-line parser is used — no packages are installed).
2. Prints a GitHub-Actions-style log with a workflow header, trigger info, the
   `build` job on `ubuntu-latest`, and a `[ step N ] <name>` line per step with
   realistic timestamps and per-step durations.
3. Simulates the `actions/checkout@v4` step (`checkout simulated`).
4. **Actually executes** the `run:` command of the `Run CI` step with
   `subprocess` (`shell=True`) and captures its real stdout/stderr.
5. Reports `Process completed with exit code 0` and a **SUCCESS** status.

Run it with:

```powershell
$env:PYTHONIOENCODING='utf-8'
python "C:\Users\soheb\OneDrive\Documents\Default Project\program8-ci\ci_runner.py"
```

> Note: the target runner is `ubuntu-latest` (bash), where `echo "..."` prints
> the bare string. The local Windows shell is `cmd.exe`, which echoes the
> surrounding quotes literally; the runner normalises that shell artifact so the
> captured output matches the ubuntu result: `Build and Test Successful`.

### Result
```
Process completed with exit code 0
SUCCESS
```

## Outputs / files
| File | Description |
|------|-------------|
| `.github/workflows/deploy.yml` | The CI workflow definition |
| `ci_runner.py` | Local mini CI runner + HTML report generator |
| `run-log.txt` | Raw captured log of the pipeline run |
| `ci-run-output.html` | Self-contained page styled like the GitHub Actions run UI |

Open `ci-run-output.html` in a browser to see the run presented like a real
GitHub Actions page (workflow box with a green check, the `build` job, both
steps with their logs, and an overall **Success** badge).

## Notes
- No files outside the `program8-ci` folder were modified.
- `git` is not installed in this environment, so Git/GitHub operations
  (commit, push, Actions runner) are simulated as described above.
