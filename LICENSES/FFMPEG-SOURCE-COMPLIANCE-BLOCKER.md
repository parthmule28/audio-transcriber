# FFmpeg source-compliance release blocker

**Status: unresolved; do not publish or redistribute the Windows release ZIP.**

The approved packaging plan intentionally retains the unpinned BtbN URL for
`ffmpeg-master-latest-win64-gpl.zip`. The fetcher records the fetched archive's
SHA-256 for traceability, but that digest is not pinned and does not identify or
prove the exact corresponding source. The fetched archive currently supplies a
license file but no source archive or written source offer. The repository has
no evidence establishing the matching source revision, build recipe, patches,
or other linked-library notices for the current binary.

`packaging/build_release.py` calls the license-material collector before writing
the ZIP. It fails closed unless `packaging/ffmpeg-source-compliance/` contains:

- `ffmpeg-corresponding-source.tar.xz`: the exact source and build recipe for
  the current binary (must include FFmpeg source files and a build recipe);
- `SOURCE-METADATA.txt`: the current fetched binary archive SHA-256, source
  archive SHA-256, source archive filename, maintainer identity, and verification
  evidence; and
- `SOURCE-OFFER.md`: a substantive written offer identifying both exact hashes
  and where the corresponding source is supplied (the release package includes
  the source archive).

The packager hashes the source archive, checks the binary hash against the
metadata emitted by the *current* `latest` download, validates that the source
archive can be read, checks for source/build files, and includes the source and
offer in the ZIP. A changed upstream `latest` archive therefore invalidates old
source metadata. Automated checks cannot establish legal sufficiency or prove
that a maintainer's correspondence review is correct: the maintainer must verify
the precise BtbN build revision, source/configuration/patch correspondence, and
all additional notices before adding these materials. Until that evidence exists,
the workflow is expected to fail before the release ZIP is produced and before a
GitHub Release can be published.

This repository makes no claim that redistribution is currently compliant.
