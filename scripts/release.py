#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import shutil


def sh(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True, text=True).strip()


def git_last_tag() -> str:
    try:
        return sh("git describe --tags --abbrev=0")
    except subprocess.CalledProcessError:
        return ""


def build_changelog(since_tag: str) -> str:
    rng = f"{since_tag}..HEAD" if since_tag else "HEAD"
    try:
        log = sh(f'git log --pretty=format:"%h %s" {rng}')
    except subprocess.CalledProcessError:
        log = ""
    lines = ["# Changelog", ""]
    if since_tag:
        lines.append(f"Changes since {since_tag}:")
    else:
        lines.append("Initial release:")
    lines.append("")
    lines.extend(log.splitlines() or ["(no commits found)"])
    lines.append("")
    # Optional KPI snippet: include latest daily digest if present
    dig_dir = "artifacts/digest"
    if os.path.isdir(dig_dir):
        try:
            files = sorted([f for f in os.listdir(dig_dir) if f.endswith(".json")])
        except Exception:
            files = []
        if files:
            kpi_path = os.path.join(dig_dir, files[-1])
            lines.append("## KPI (latest digest)")
            try:
                with open(kpi_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # print first few keys deterministically
                for k in sorted(list(data.keys()))[:10]:
                    try:
                        v = data[k]
                    except Exception:
                        v = None
                    lines.append(f"- {k}: {v}")
            except Exception as e:
                lines.append(f"(failed to read KPIs: {e})")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="vX.Y.Z")
    ap.add_argument("--dry-run", action="store_true", help="do not create a git tag; write changelog only")
    ap.add_argument("--validate", action="store_true", help="run bundle-auto even in dry-run")
    args = ap.parse_args()

    ver = str(args.version)
    if not ver.startswith("v"):
        print("version must start with 'v' (e.g., v0.1.0)", file=sys.stderr)
        sys.exit(2)

    # READY-gate: heavy step. Skip by default for dry-run unless --validate is set
    if (not args.dry_run) or args.validate:
        try:
            subprocess.check_call("make bundle-auto", shell=True)
        except Exception:
            try:
                subprocess.check_call(
                    f"{sys.executable} tools/ci/full_stack_validate.py --accept --artifacts-dir artifacts",
                    shell=True,
                )
            except subprocess.CalledProcessError:
                print("bundle-auto failed", file=sys.stderr)
                sys.exit(1)

    since = git_last_tag()
    changelog = build_changelog(since)
    fname = f"CHANGELOG_{ver}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(changelog)
    print(f"Wrote {fname}")

    if args.dry_run:
        print(f"[dry-run] would tag {ver}")
        return

    # If git is not available, behave like dry-run after writing changelog
    if not shutil.which("git"):
        print("git not found, falling back to --dry-run")
        return

    # Create annotated tag
    msg = f"Release {ver}\n\n" + changelog
    # Avoid double quotes in shell string
    safe_msg = msg.replace('"', "'")
    subprocess.check_call(f'git tag -a {ver} -m "{safe_msg}"', shell=True)
    print(f"Tagged {ver}. Use: git push origin {ver}")


if __name__ == "__main__":
    main()


