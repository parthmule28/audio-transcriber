# FFmpeg source/build validation status

The prior blocker described the unpinned BtbN GPL binary archive. That packaging path has been replaced and this document must not be used as instructions for new builds.

The replacement pins official FFmpeg 9.0.2 source by SHA-256, verifies the detached release signature against the pinned release-key fingerprint, builds shared libraries with GPL/version-3/nonfree/network features disabled, and includes the source archive, signature, key, license, build recipe, toolchain notices, and generated provenance in the Windows ZIP. The packager fails closed if those materials or the hashes of the executables and FFmpeg DLLs are absent or inconsistent.

**Validation remains pending until Windows CI successfully completes the source build, FFmpeg feature smoke test, application self-test, license/source collection, and ZIP inspection. Do not treat Linux unit tests or this document as proof that the Windows build or redistribution review has succeeded.** No legal-compliance guarantee is made; review the exact output and all applicable notices before redistribution.
