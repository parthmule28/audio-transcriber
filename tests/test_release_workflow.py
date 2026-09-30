from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_workflow_requires_manual_version_and_preserves_tag_versioning():
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert re.search(
        r"workflow_dispatch:\s*\n\s+inputs:\s*\n\s+version:\s*\n"
        r"\s+description:.*\n\s+required: true\n\s+type: string",
        workflow,
    )
    assert "RELEASE_VERSION: ${{ inputs.version }}" in workflow
    assert 'version="$RELEASE_VERSION"' in workflow
    assert 'version="${GITHUB_REF_NAME#v}"' in workflow
    assert 'python packaging/build_release.py --version "$version"' in workflow
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in workflow
