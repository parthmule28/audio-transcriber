from __future__ import annotations

import re
from pathlib import Path

from audio_transcriber import __version__

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


def test_readme_download_instructions_do_not_embed_a_drifting_version():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert f"AudioTranscriber-v{__version__}-win-x64.zip" not in readme
    assert "latest GitHub Release" in readme


def test_workflow_builds_and_smoke_tests_pinned_ffmpeg_before_packaging():
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "runs-on: windows-2022" in workflow
    assert "uses: msys2/setup-msys2@v2" in workflow
    assert "msystem: UCRT64" in workflow
    for package in (
        "mingw-w64-ucrt-x86_64-gcc",
        "mingw-w64-ucrt-x86_64-nasm",
        "gnupg",
    ):
        assert package in workflow
    source_build = workflow.index("packaging/build_ffmpeg.sh")
    smoke_test = workflow.index("packaging/smoke_test_ffmpeg.py")
    package = workflow.index("python packaging/build_release.py --version")
    self_test = workflow.index("Self-test packaged application")
    assert source_build < smoke_test < package < self_test
    assert "AudioTranscriber.exe --self-test" in workflow


def test_manual_workflow_uploads_only_a_windows_test_artifact_and_never_releases():
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "name: Upload Windows test archive artifact" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert "name: AudioTranscriber-windows-test" in workflow
    assert "path: dist/AudioTranscriber-v*-win-x64.zip" in workflow
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in workflow
    release_step = workflow.index("name: Publish GitHub Release")
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in workflow[release_step:]
    assert "secrets." not in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert ".wav" in workflow and "no step uploads" in workflow.lower()


def test_readme_explains_how_to_get_test_artifact_without_a_release():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "AudioTranscriber-windows-test" in readme
    assert "Run workflow" in readme
    assert "does not create a GitHub Release" in readme
    assert "ffmpeg-9.0.2.tar.xz" in readme
    assert "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e" in readme
