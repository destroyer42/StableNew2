"""Utilities for running Codex AutoFix inside CI."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass

import requests

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover - handled during CI setup
    raise SystemExit("openai package is required to run Codex AutoFix") from exc


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def format_summary(self, limit: int = 4000) -> str:
        def tail(value: str) -> str:
            if len(value) <= limit:
                return value
            return f"...\n{value[-limit:]}"

        return textwrap.dedent(
            f"""
            Command: {self.command}
            Exit code: {self.returncode}

            STDOUT:\n{tail(self.stdout) or "(empty)"}

            STDERR:\n{tail(self.stderr) or "(empty)"}
            """
        ).strip()


def run_command(command: str, *, env: dict[str, str] | None = None) -> CommandResult:
    process = subprocess.run(  # noqa: S603,S607 - intentional shell invocation for composite commands
        command,
        shell=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return CommandResult(
        command=command,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def gather_repo_snapshot() -> str:
    snapshot_parts: list[str] = []
    for title, command in (
        ("HEAD", "git rev-parse HEAD"),
        ("Status", "git status --short"),
        ("Tracked files", "git ls-files"),
    ):
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
        )
        body = result.stdout.strip() or result.stderr.strip() or "(empty)"
        snapshot_parts.append(f"### {title}\n{body}")
    return "\n\n".join(snapshot_parts)


def render_prompt(
    repo: str,
    pr_number: int,
    head_sha: str,
    command_result: CommandResult,
    *,
    snapshot: str,
    run_url: str,
) -> str:
    summary = command_result.format_summary()
    return textwrap.dedent(
        f"""
        You are Codex, an expert Python engineer helping on the repository `{repo}`.
        A pull request (#{pr_number}) currently fails when CI runs `{command_result.command}`.
        The workflow execution details are available at {run_url}.

        Provide the minimal set of changes required to make the command succeed.
        Constraints:
        - Only touch files that already exist in the repository.
        - Prefer the smallest possible diff that directly addresses the failure.
        - Return your answer as GitHub-flavored Markdown with these sections:
          1. **Root Cause** – 1-3 concise sentences.
          2. **Proposed Patch** – a single ```diff code block containing the unified diff.
             Make sure the diff applies cleanly with `patch -p1`.
          3. **Validation** – step-by-step instructions the reviewer can run locally to confirm the fix.

        ## Repository snapshot
        {snapshot}

        ## Command summary
        {summary}
        """
    ).strip()


def request_codex_suggestion(prompt: str, *, api_key: str) -> str:
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model="gpt-5-codex",
        input=[
            {"role": "system", "content": "You are Codex, an expert software engineer."},
            {"role": "user", "content": prompt},
        ],
        max_output_tokens=1200,
    )

    # Parse response using OpenAI chat completion API format
    try:
        return response.choices[0].message.content.strip()
    except (AttributeError, IndexError) as exc:
        raise RuntimeError("Codex response did not contain any text output") from exc


def post_comment(*, repo: str, pr_number: int, body: str, token: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"body": body},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to post comment (status={response.status_code}): {response.text}"
        )


def build_comment(
    *,
    command_result: CommandResult,
    suggestion: str,
    run_url: str,
) -> str:
    status = "succeeded" if command_result.succeeded else "failed"
    summary = command_result.format_summary(limit=2000)
    return textwrap.dedent(
        f"""
        Codex AutoFix run ({status}) • [Workflow logs]({run_url})

        <details>
        <summary>Test command output</summary>

        ```
        {summary}
        ```

        </details>

        ---

        {suggestion}
        """
    ).strip()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex AutoFix and post a PR comment")
    parser.add_argument("--repo", required=True, help="owner/repo slug")
    parser.add_argument("--pr", type=int, required=True, help="Pull request number")
    parser.add_argument(
        "--head-sha",
        default="",
        help="Head commit SHA for logging only",
    )
    parser.add_argument(
        "--command",
        default=os.environ.get("CODEX_AUTOFIX_COMMAND", "pytest --maxfail=1 -q"),
        help="Command to run before invoking Codex",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip executing the failing command (useful for dry runs)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set for Codex AutoFix")

    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise RuntimeError("GITHUB_TOKEN must be provided to post PR comments")

    command_result = CommandResult(args.command, 0, "(skipped)", "")
    if not args.skip_tests:
        command_result = run_command(args.command)

    run_url = (
        f"https://github.com/{args.repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')}"
    )
    snapshot = gather_repo_snapshot()
    prompt = render_prompt(
        args.repo,
        args.pr,
        args.head_sha,
        command_result,
        snapshot=snapshot,
        run_url=run_url,
    )

    suggestion = request_codex_suggestion(prompt, api_key=api_key)
    comment = build_comment(
        command_result=command_result,
        suggestion=suggestion,
        run_url=run_url,
    )
    post_comment(repo=args.repo, pr_number=args.pr, body=comment, token=github_token)

    print("Codex AutoFix comment posted successfully")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # pragma: no cover - ensures failure details in logs
        print(f"Codex AutoFix failed: {exc}", file=sys.stderr)
        raise
