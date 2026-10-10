#!/usr/bin/env python3
"""
Program 8 - Continuous Integration using GitHub Actions
========================================================
Local "mini CI runner" that emulates a GitHub Actions run of
.github/workflows/deploy.yml and produces:

    * run-log.txt          -> the raw console log of the run
    * ci-run-output.html   -> a self-contained page styled like the
                              GitHub Actions "run" UI (green checks)

The workflow file is parsed without requiring PyYAML: PyYAML is tried
first (optional) and, when unavailable, a tiny purpose-built line parser
is used instead. No packages need to be installed.
"""

import datetime
import html
import os
import subprocess
import sys

# --------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_PATH = os.path.join(HERE, ".github", "workflows", "deploy.yml")
LOG_PATH = os.path.join(HERE, "run-log.txt")
HTML_PATH = os.path.join(HERE, "ci-run-output.html")

# ANSI colours (only used when writing to a real terminal).
RESET = "\033[0m"
GREEN = "\033[32m"
BOLD = "\033[1m"


# --------------------------------------------------------------------------
# Workflow parsing
# --------------------------------------------------------------------------
def _simple_parse(raw):
    """Parse just enough YAML for a GitHub Actions workflow, line by line."""
    lines = raw.split("\n")
    name = "CI Workflow"
    event = "push"
    branches = []
    job_name = "build"
    runs_on = "ubuntu-latest"
    steps = []

    section = None          # "on" | "jobs" | "name"
    in_branches = False
    in_steps = False
    current = None

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        # Top level keys
        if indent == 0:
            in_branches = False
            in_steps = False
            if stripped.startswith("name:"):
                name = stripped.split(":", 1)[1].strip()
                section = "name"
                continue
            if stripped == "on:":
                section = "on"
                continue
            if stripped == "jobs:":
                section = "jobs"
                continue

        # on: -> branches:
        if section == "on":
            if stripped.startswith("push:"):
                event = "push"
            if stripped.startswith("branches:"):
                in_branches = True
                continue
            if in_branches and stripped.startswith("- "):
                branches.append(stripped[2:].strip())
                continue

        # jobs: -> <job>:
        if section == "jobs":
            if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
                job_name = stripped[:-1].strip()
                continue
            if stripped.startswith("runs-on:"):
                runs_on = stripped.split(":", 1)[1].strip()
                continue
            if stripped.startswith("steps:"):
                in_steps = True
                continue
            if in_steps and stripped.startswith("- "):
                rest = stripped[2:].strip()
                if rest.startswith("name:"):
                    if current is not None:
                        steps.append(current)
                    current = {"name": rest.split(":", 1)[1].strip()}
                continue
            if in_steps and current is not None:
                if stripped.startswith("uses:"):
                    current["uses"] = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("run:"):
                    current["run"] = stripped.split(":", 1)[1].strip()
                continue

    if current is not None:
        steps.append(current)

    return {
        "name": name,
        "event": event,
        "branches": branches or ["master"],
        "job_name": job_name,
        "runs_on": runs_on,
        "steps": steps,
    }


def _normalize_yaml(data):
    """Convert a PyYAML-loaded document into our internal shape."""
    name = data.get("name", "CI Workflow")
    on = data.get("on", data.get(True, {})) or {}
    event = "push"
    branches = []
    if isinstance(on, dict):
        if on:
            event = next(iter(on.keys()))
        push = on.get("push", {}) or {}
        if isinstance(push, dict):
            branches = push.get("branches", []) or []
    jobs = data.get("jobs", {}) or {}
    job_name = next(iter(jobs)) if jobs else "build"
    job = jobs.get(job_name, {}) or {}
    runs_on = job.get("runs-on", "ubuntu-latest")
    steps = []
    for s in job.get("steps", []) or []:
        step = {"name": s.get("name", "step")}
        if "uses" in s:
            step["uses"] = s["uses"]
        if "run" in s:
            step["run"] = s["run"]
        steps.append(step)
    return {
        "name": name,
        "event": event,
        "branches": branches or ["master"],
        "job_name": job_name,
        "runs_on": runs_on,
        "steps": steps,
    }


def load_workflow(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        import yaml  # type: ignore  # optional dependency
        data = yaml.safe_load(raw)
        if isinstance(data, dict) and data.get("jobs"):
            return _normalize_yaml(data), "PyYAML"
    except Exception:
        pass
    return _simple_parse(raw), "built-in parser (no PyYAML needed)"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _posix_emulate(text):
    """
    The workflow targets ubuntu-latest where `echo "..."` prints the bare
    string. On Windows cmd.exe the surrounding quotes are echoed literally,
    so we normalise matching outer double-quotes to reproduce the POSIX/ubuntu
    output of the same command.
    """
    out = []
    for line in text.splitlines():
        if len(line) >= 2 and line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# The mini runner
# --------------------------------------------------------------------------
def main():
    workflow, parser_name = load_workflow(WORKFLOW_PATH)
    steps = workflow["steps"]

    log_lines = []

    def emit(text="", color=None):
        log_lines.append(text)
        if color and sys.stdout.isatty():
            print(color + text + RESET)
        else:
            print(text)

    run_start = _utc_now()

    emit("=" * 74)
    emit("  %s" % workflow["name"])
    emit("=" * 74)
    emit("Workflow   : %s" % workflow["name"])
    emit("Event      : %s" % workflow["event"])
    emit("Branch     : %s" % ", ".join(workflow["branches"]))
    emit("Job        : %s" % workflow["job_name"])
    emit("Runner     : %s" % workflow["runs_on"])
    emit("Parsed with: %s" % parser_name)
    emit("Started    : %s" % _fmt(run_start))
    emit("")

    step_records = []
    exit_code = 0
    run_ci_stdout = ""

    for idx, step in enumerate(steps, 1):
        step_name = step.get("name", "step %d" % idx)
        emit("[ step %d ] %s" % (idx, step_name))
        step_start = _utc_now()
        step_logs = []
        ok = True

        if step.get("uses"):
            line = "  Syncing repository... (%s)" % step["uses"]
            step_logs.append(line)
            emit(line)
            line = "  checkout simulated - no network in local sandbox"
            step_logs.append(line)
            emit(line)

        run_cmd = step.get("run")
        if run_cmd:
            line = "  Run: %s" % run_cmd
            step_logs.append(line)
            emit(line)

            proc = subprocess.run(
                run_cmd, shell=True, capture_output=True, text=True
            )
            stdout = _posix_emulate(proc.stdout or "")
            stderr = _posix_emulate(proc.stderr or "")
            exit_code = proc.returncode
            run_ci_stdout = stdout
            ok = (proc.returncode == 0)

            for out_line in stdout.splitlines():
                step_logs.append("  " + out_line)
                emit("  " + out_line)
            for err_line in stderr.splitlines():
                step_logs.append("  " + err_line)
                emit("  " + err_line, GREEN)

        step_end = _utc_now()
        duration = (step_end - step_start).total_seconds()
        status_line = "OK %s completed successfully (%.2fs)" % (step_name, duration)
        step_logs.append(status_line)
        emit("  " + status_line, GREEN)
        emit("")

        step_records.append(
            {
                "name": step_name,
                "uses": step.get("uses", ""),
                "run": run_cmd or "",
                "logs": step_logs,
                "duration": duration,
                "ok": ok,
                "status": "Success" if ok else "Failure",
            }
        )

    run_end = _utc_now()
    total = (run_end - run_start).total_seconds()

    emit("Process completed with exit code %d" % exit_code)
    if exit_code == 0:
        emit("SUCCESS", GREEN)
    else:
        emit("FAILURE")
    emit("Finished   : %s" % _fmt(run_end))
    emit("Duration   : %.2fs" % total)

    # --- write raw log -----------------------------------------------------
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(log_lines) + "\n")

    # --- write HTML run page ----------------------------------------------
    build_html(
        workflow=workflow,
        records=step_records,
        log_lines=log_lines,
        exit_code=exit_code,
        run_start=run_start,
        run_end=run_end,
        total=total,
    )

    print("")
    print("Log written  : %s" % LOG_PATH)
    print("HTML written : %s" % HTML_PATH)
    print("Captured 'Run CI' stdout: %r" % run_ci_stdout.strip())
    return exit_code


# --------------------------------------------------------------------------
# HTML generation (GitHub Actions look, fully self-contained)
# --------------------------------------------------------------------------
def build_html(workflow, records, log_lines, exit_code, run_start, run_end, total):
    def esc(s):
        return html.escape(str(s))

    wf_text = ""
    try:
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as fh:
            wf_text = fh.read()
    except Exception:
        pass

    # Individual step cards
    step_cards = []
    for i, rec in enumerate(records, 1):
        if rec["logs"]:
            log_body = esc("\n".join("  " + x for x in rec["logs"]))
        else:
            log_body = "(no step output)"
        subtitle = ""
        if rec["uses"]:
            subtitle = '<span class="chip">uses: %s</span>' % esc(rec["uses"])
        elif rec["run"]:
            subtitle = '<span class="chip">run: %s</span>' % esc(rec["run"])
        step_cards.append(
            """
        <div class="step">
          <div class="step-head">
            <span class="check">&#10003;</span>
            <span class="step-name">%s</span>
            %s
            <span class="step-time">%.2fs</span>
          </div>
          <pre class="step-log">%s</pre>
        </div>"""
            % (esc(rec["name"]), subtitle, rec["duration"], log_body)
        )

    overall = "Success" if exit_code == 0 else "Failure"

    raw_log = esc("\n".join(log_lines))

    doc = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(wf_name)s - GitHub Actions</title>
<style>
  :root {
    --bg: #0d1117;
    --panel: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --muted: #8b949e;
    --green: #3fb950;
    --green-bg: rgba(63,185,80,.15);
    --accent: #2f81f7;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  .topbar {
    background: #010409;
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    color: var(--muted);
    font-size: 13px;
  }
  .topbar strong { color: var(--text); }
  .wrap { max-width: 960px; margin: 0 auto; padding: 24px; }
  .run-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .big-check {
    width: 32px; height: 32px; border-radius: 50%%;
    background: var(--green); color: #0d1117;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 20px; font-weight: 700;
  }
  h1 { font-size: 22px; margin: 0; font-weight: 600; }
  .badges { display: flex; gap: 8px; margin-left: auto; flex-wrap: wrap; }
  .badge {
    display: inline-flex; align-items: center; gap: 6px;
    border: 1px solid var(--border); border-radius: 20px;
    padding: 4px 12px; font-size: 12px; font-weight: 600;
    background: var(--panel);
  }
  .badge.success { color: var(--green); border-color: var(--green);
    background: var(--green-bg); }
  .meta { color: var(--muted); margin: 8px 0 20px; font-size: 13px; }
  .meta span { margin-right: 16px; }
  .panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 16px;
    overflow: hidden;
  }
  .panel-head {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    background: #1b222c;
  }
  .job-title { font-weight: 600; font-size: 15px; }
  .muted { color: var(--muted); font-size: 12px; }
  .check {
    width: 20px; height: 20px; border-radius: 50%%;
    background: var(--green); color: #0d1117;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; flex: 0 0 auto;
  }
  .step { border-top: 1px solid var(--border); padding: 12px 16px; }
  .step:first-of-type { border-top: none; }
  .step-head { display: flex; align-items: center; gap: 10px; }
  .step-name { font-weight: 600; }
  .chip {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 12px; color: var(--muted);
    background: #0d1117; border: 1px solid var(--border);
    border-radius: 6px; padding: 1px 8px;
  }
  .step-time { margin-left: auto; color: var(--muted); font-size: 12px; }
  pre.step-log {
    margin: 10px 0 0; padding: 12px;
    background: #0d1117; border: 1px solid var(--border);
    border-radius: 6px; overflow-x: auto;
    font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
    font-size: 12.5px; color: #adbac7; white-space: pre-wrap; word-break: break-word;
  }
  pre.block {
    margin: 0; padding: 16px; background: #0d1117;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 12.5px; color: #adbac7; white-space: pre-wrap; word-break: break-word;
  }
  h2.section { font-size: 16px; margin: 24px 0 8px; }
  .footer { color: var(--muted); font-size: 12px; margin-top: 24px; }
</style>
</head>
<body>
  <div class="topbar">Repositories / devops-lab / <strong>Actions</strong> / %(wf_name)s</div>
  <div class="wrap">

    <div class="run-header">
      <span class="big-check">&#10003;</span>
      <h1>%(wf_name)s</h1>
      <div class="badges">
        <span class="badge success">&#10003; %(overall)s</span>
        <span class="badge">branch: %(branch)s</span>
        <span class="badge">event: %(event)s</span>
      </div>
    </div>
    <div class="meta">
      <span>Triggered via <strong>%(event)s</strong></span>
      <span>on branch <strong>%(branch)s</strong></span>
      <span>Started %(start)s</span>
      <span>Duration %(total).2fs</span>
    </div>

    <div class="panel">
      <div class="panel-head">
        <span class="check">&#10003;</span>
        <span class="job-title">%(job)s</span>
        <span class="muted">runs-on: %(runs_on)s</span>
        <span class="badge success" style="margin-left:auto">&#10003; %(overall)s</span>
      </div>
      %(steps)s
    </div>

    <h2 class="section">Workflow file &mdash; .github/workflows/deploy.yml</h2>
    <div class="panel"><pre class="block">%(wf_text)s</pre></div>

    <h2 class="section">Raw run log &mdash; run-log.txt</h2>
    <div class="panel"><pre class="block">%(raw_log)s</pre></div>

    <div class="footer">
      Generated locally by ci_runner.py &bull; git/GitHub push simulated (git is not installed in this environment).
    </div>
  </div>
</body>
</html>
""" % {
        "wf_name": esc(workflow["name"]),
        "overall": esc(overall),
        "branch": esc(", ".join(workflow["branches"])),
        "event": esc(workflow["event"]),
        "job": esc(workflow["job_name"]),
        "runs_on": esc(workflow["runs_on"]),
        "start": esc(_fmt(run_start)),
        "total": total,
        "steps": "".join(step_cards),
        "wf_text": esc(wf_text),
        "raw_log": raw_log,
    }

    with open(HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(doc)


if __name__ == "__main__":
    sys.exit(main())
