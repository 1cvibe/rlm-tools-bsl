#!/bin/bash
set -e

echo "=== rlm-tools-bsl entrypoint ==="

# --- 1. Get current installed version ---
CURRENT_VERSION=$(python -c "import importlib.metadata; print(importlib.metadata.version('rlm-tools-bsl'))" 2>/dev/null || echo "unknown")
echo "Current version: $CURRENT_VERSION"

# --- 2. Version check / update ---
RLM_VERSION="${RLM_VERSION:-}"

if [ -z "$RLM_VERSION" ] || [ "$RLM_VERSION" = "latest" ]; then
    # Auto-update: check PyPI for latest version
    echo "Checking PyPI for latest version..."
    PYPI_VERSION=$(python -c "
import urllib.request, json
try:
    data = json.loads(urllib.request.urlopen('https://pypi.org/pypi/rlm-tools-bsl/json', timeout=10).read())
    print(data['info']['version'])
except Exception as e:
    print(f'PYPI_ERROR:{e}')
" 2>/dev/null)

    if echo "$PYPI_VERSION" | grep -q "^PYPI_ERROR:"; then
        echo "WARNING: Cannot reach PyPI (${PYPI_VERSION#PYPI_ERROR:}), continuing with current version"
    elif [ "$PYPI_VERSION" != "$CURRENT_VERSION" ]; then
        echo "Updating: $CURRENT_VERSION -> $PYPI_VERSION"
        pip install --user --no-cache-dir --upgrade rlm-tools-bsl || echo "WARNING: pip upgrade failed, continuing with current version"
    else
        echo "Already up to date"
    fi
else
    # Pinned version
    if [ "$RLM_VERSION" != "$CURRENT_VERSION" ]; then
        echo "Pinned version requested: $RLM_VERSION (current: $CURRENT_VERSION)"
        pip install --user --no-cache-dir "rlm-tools-bsl==$RLM_VERSION" || echo "WARNING: pip install ==$RLM_VERSION failed, continuing with $CURRENT_VERSION"
    else
        echo "Pinned version $RLM_VERSION already installed"
    fi
fi

# --- 3. Update indexes for registered projects ---
echo "Checking registered projects for index updates..."

PROJECTS_TO_UPDATE=$(python -c "
import sys
try:
    from rlm_tools_bsl.projects import get_registry
    from rlm_tools_bsl.bsl_index import get_index_db_path
except Exception as e:
    print(f'WARNING: cannot import project API: {e}', file=sys.stderr)
    sys.exit(0)
try:
    registry = get_registry()
    projects = registry.list_projects()
except Exception as e:
    print(f'WARNING: cannot read project registry: {e}', file=sys.stderr)
    sys.exit(0)
if not projects:
    print('No registered projects, skipping index update', file=sys.stderr)
    sys.exit(0)
for p in projects:
    name, path = p.get('name','?'), p.get('path','')
    try:
        db = get_index_db_path(path)
        if db.exists():
            print(f'{name}\t{path}')
        else:
            print(f'Skipping {name}: no index found', file=sys.stderr)
    except Exception as e:
        print(f'WARNING: error checking {name}: {e}', file=sys.stderr)
")

echo "$PROJECTS_TO_UPDATE" | while IFS=$'\t' read -r name path; do
    [ -z "$path" ] && continue
    echo "Updating index: $name ($path)"
    (rlm-bsl-index index update "$path" 2>&1) || echo "WARNING: index update failed for $name"
done

# --- 4. Start MCP server ---
echo "Starting rlm-tools-bsl server..."
exec rlm-tools-bsl
