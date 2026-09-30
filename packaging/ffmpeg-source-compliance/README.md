# Required FFmpeg source-compliance inputs

This directory intentionally contains no source bundle yet. The current
`ffmpeg-master-latest-win64-gpl.zip` download has no established matching source
or offer here, so release packaging remains blocked.

To unblock a future release, a maintainer must establish correspondence for the
exact binary archive fetched by that build, record review evidence, and provide
the three files listed in
[`../../LICENSES/FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md`](../../LICENSES/FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md).
`SOURCE-METADATA.txt` must contain these exact fields:

```text
Binary archive SHA-256: <64 lowercase hex digits from FFMPEG-ARCHIVE-METADATA.txt>
Source archive SHA-256: <64 lowercase hex digits for the source tarball>
Source archive: ffmpeg-corresponding-source.tar.xz
Corresponding source verified by: <maintainer name>
Verification evidence: <specific revision/configuration/patch/build provenance checked>
```

`SOURCE-OFFER.md` must state both hashes and that the exact source is supplied
with the release. Do not fill these fields by copying an unverified digest or
assert compliance without source/provenance evidence. The `latest` URL stays
unpinned per the approved v1 plan; a changed binary digest blocks reuse of old
source materials.
