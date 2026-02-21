import requests
import json
import sys

if len(sys.argv) != 3:
    print("Usage: python script.py <owner> <repo>")
    sys.exit(1)

owner, repo = sys.argv[1], sys.argv[2]
url = f"https://api.github.com/repos/{owner}/{repo}"

try:
    r = requests.get(url)
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print("Error:", e)

default_branch: str = r.json().get("default_branch", "main")

# Step 2: Get the recursive tree of the default branch
tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
tree_data = requests.get(tree_url).json()

print(json.dumps(tree_data, indent=2))