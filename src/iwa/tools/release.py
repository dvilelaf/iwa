#!/usr/bin/env python3
"""Release helper script.

Usage: python release.py <version>
"""
import argparse
import subprocess  # nosec: B404
import sys
from typing import NoReturn


def run(cmd: str, check: bool = True, capture: bool = False) -> str:
    """Run a shell command."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,  # nosec: B602
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None
        )
        return result.stdout.strip() if capture else ""
    except subprocess.CalledProcessError as e:
        if capture:
            print(f"Error output: {e.stderr}")
        sys.exit(e.returncode)

def error(msg: str) -> NoReturn:
    """Print error and exit."""
    print(f"❌ Error: {msg}")
    sys.exit(1)

def info(msg: str) -> None:
    """Print info message."""
    print(f"🚀 {msg}")

def confirm(question: str) -> bool:
    """Ask for user confirmation."""
    while True:
        try:
            choice = input(f"{question} [y/N] ").lower()
            if not choice or choice == 'n':
                return False
            if choice == 'y':
                return True
        except EOFError:
            return False

def main() -> None:
    """Execute the release process."""
    parser = argparse.ArgumentParser(description="Create a new release")
    parser.add_argument("version", help="Version tag (e.g., 0.1.0)")
    args = parser.parse_args()

    version = args.version
    if version.startswith("v"):
        version = version[1:]
    tag = f"v{version}"

    # 1. Check git status
    print("Checking git status...")
    status = run("git status --porcelain", capture=True)
    if status:
        error("Working directory is not clean. Commit changes first.")

    try:
        # User requested SSH agent usage. If origin is HTTPS, we try to use SSH for the check explicitly.
        # This bypasses the HTTPS auth prompt if the user has SSH keys configured.
        origin_url = run("git remote get-url origin", capture=True)
        check_url = origin_url
        if origin_url.startswith("https://github.com/"):
            # Convert https://github.com/user/repo.git -> git@github.com:user/repo.git
            ssh_url = origin_url.replace("https://github.com/", "git@github.com:")
            check_url = ssh_url
            print(f"checking remote tags via SSH ({ssh_url})...")

        # Use ls-remote on the specific URL (SSH) to check tags without prompting for HTTPS creds
        exists_remotely = run(f"git ls-remote --tags {check_url} {tag}", check=False, capture=True)

    except Exception:
        # fetch failed (likely auth), assume we can proceed to push (which might prompt or work if user is right)
        print("⚠️  Could not fetch remote info (auth needed?). Assuming tag is new remotely.")
        exists_remotely = ""

    # 3. Check if tag exists
    exists_locally = run(f"git rev-parse {tag}", check=False, capture=True)

    if exists_locally or exists_remotely:
        print(f"⚠️  Tag {tag} already exists!")
        if not confirm("Do you want to FORCE update it (delete and overwrite)?"):
            error("Aborted by user.")

        info(f"Force updating {tag}...")
        run(f"git tag -f {tag}")
        # Push to the explicit URL (likely SSH) to avoid HTTPS prompts
        run(f"git push -f {check_url} {tag}")
        print(f"✅ Tag {tag} force updated. GitHub Actions triggered.")

    else:
        info(f"Preparing to release {tag}...")
        if not confirm("Are you sure? This will trigger a deployment to PyPI and DockerHub"):
            error("Aborted by user.")

        run(f"git tag {tag}")
        # Push to the explicit URL (likely SSH) to avoid HTTPS prompts
        run(f"git push {check_url} {tag}")
        print(f"✅ Release {tag} triggered! Check GitHub Actions.")

if __name__ == "__main__":
    main()
