"""
GitHub API Explorer — development runner.

Usage:
    python runners/github_runner.py <owner> <repo>

Prints the raw metadata and recursive file-tree responses from the
GitHub API so you can inspect the data before the production client
post-processes it.  Not part of the application; never imported.
"""

import json
import sys

import httpx


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python runners/github_runner.py <owner> <repo>")
        sys.exit(1)

    owner, repo = sys.argv[1], sys.argv[2]

    with httpx.Client() as client:
        # Step 1: repo metadata
        meta_url = f"https://api.github.com/repos/{owner}/{repo}"
        print(f"\n--- GET {meta_url} ---")
        r = client.get(meta_url)
        meta = r.json()
        print(json.dumps(meta, indent=2))

        default_branch: str = meta.get("default_branch", "main")

        # Step 2: recursive file tree
        tree_url = (
            f"https://api.github.com/repos/{owner}/{repo}"
            f"/git/trees/{default_branch}?recursive=1"
        )
        print(f"\n--- GET {tree_url} ---")
        tree = client.get(tree_url).json()
        print(json.dumps(tree, indent=2))


if __name__ == "__main__":
    main()
