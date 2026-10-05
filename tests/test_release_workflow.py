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
        "mingw-w64-ucrt-x86_64-python",
        "gnupg",
    ):
        assert package in workflow
    source_build = workflow.index("packaging/build_ffmpeg.sh")
    smoke_test = workflow.index("packaging/smoke_test_ffmpeg.py")
    package = workflow.index("python packaging/build_release.py --version")
    self_test = workflow.index("Self-test packaged application")
    syntax_start = workflow.index("- name: Check FFmpeg build script syntax")
    tests_start = workflow.index("- name: Run tests")
    tests_end = workflow.index("- name: Build pinned LGPL FFmpeg from source")
    syntax_step = workflow[syntax_start:tests_start]
    run_tests = workflow[tests_start:tests_end]
    assert source_build < smoke_test < package < self_test
    assert syntax_start < tests_start
    assert "shell: msys2 {0}" in syntax_step
    assert "bash -n packaging/build_ffmpeg.sh" in syntax_step
    assert "AudioTranscriber.exe --self-test" in workflow


def test_manual_workflow_uploads_only_a_windows_test_artifact_and_never_releases():
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    normalized = " ".join(workflow.split())

    assert "name: Upload Windows test archive artifact" in workflow
    assert (
        "if: >- github.event_name == 'workflow_dispatch' || "
        "github.ref == 'refs/heads/feat/pinned-lgpl-ffmpeg'"
    ) in normalized
    assert "name: AudioTranscriber-windows-test" in workflow
    assert "path: dist/AudioTranscriber-v*-win-x64.zip" in workflow
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in workflow
    publish_job = workflow[workflow.index("  publish:"):]
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in publish_job
    assert "secrets." not in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert ".wav" in workflow and "no step uploads" in workflow.lower()


def test_readme_explains_how_to_get_test_artifact_without_a_release():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "AudioTranscriber-windows-test" in readme
    assert "Run workflow" in readme
    assert "Neither path creates a GitHub Release" in readme
    assert "ffmpeg-9.0.2.tar.xz" in readme
    assert "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e" in readme


def test_candidate_branch_push_builds_and_uploads_without_requiring_default_branch_dispatch():
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert re.search(r"on:\s*\n\s+push:\s*\n", workflow)
    assert "github.ref == 'refs/heads/feat/pinned-lgpl-ffmpeg'" in workflow
    assert "AudioTranscriber-windows-test" in workflow
    assert "github.ref == 'refs/heads/feat/pinned-lgpl-ffmpeg'" in workflow[
        workflow.index("name: Upload Windows test archive artifact"):
    ]
    assert "from audio_transcriber import __version__" in workflow


def test_build_job_has_read_only_token_and_tag_release_uses_separate_write_job():
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    build_start = workflow.index("  release:")
    publish_start = workflow.index("  publish:")
    build_job = workflow[build_start:publish_start]
    publish_job = workflow[publish_start:]
    assert re.search(r"permissions:\s*\n\s+contents: read", build_job)
    assert "needs: release" in publish_job
    assert "contents: write" in publish_job
    assert "actions/download-artifact@v4" in publish_job
    assert "name: AudioTranscriber-release" in build_job
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in publish_job
