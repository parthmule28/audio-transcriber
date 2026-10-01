#!/usr/bin/env bash
set -euo pipefail

FFMPEG_VERSION=9.0.2
SOURCE_ARCHIVE_NAME="ffmpeg-${FFMPEG_VERSION}.tar.xz"
SOURCE_URL=https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz
SOURCE_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
RELEASE_KEY_FINGERPRINT=FCF986EA15E6E293A5644F10B4322F04D67658D8

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
output_dir="$repo_root/packaging/bin"

if [[ "${MSYSTEM:-}" != "UCRT64" || "${MINGW_PREFIX:-}" != "/ucrt64" ]]; then
    printf 'Build must run inside the MSYS2 UCRT64 environment.\n' >&2
    exit 2
fi

for tool in python gpg tar make gcc nasm sha256sum objdump pacman cygpath; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Required UCRT64 build tool is missing: %s\n' "$tool" >&2
        exit 2
    fi
done

temp_parent="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
if [[ "$temp_parent" == *:* ]]; then
    temp_parent="$(cygpath -u "$temp_parent")"
fi
work_dir="$(mktemp -d "$temp_parent/ffmpeg-${FFMPEG_VERSION}.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
mkdir -p "$work_dir/source-cache" "$work_dir/unpacked" "$work_dir/gnupg" "$work_dir/prefix" "$work_dir/stage"
chmod 700 "$work_dir/gnupg"

python "$repo_root/packaging/fetch_ffmpeg.py" "$work_dir/source-cache"
source_archive="$work_dir/source-cache/$SOURCE_ARCHIVE_NAME"
source_signature="$source_archive.asc"

actual_source_hash="$(sha256sum "$source_archive" | awk '{print $1}')"
if [[ "$actual_source_hash" != "$SOURCE_SHA256" ]]; then
    printf 'Pinned FFmpeg source digest mismatch: expected %s, got %s\n' \
        "$SOURCE_SHA256" "$actual_source_hash" >&2
    exit 1
fi

release_key="$script_dir/ffmpeg-release-key.asc"
gpg --batch --homedir "$work_dir/gnupg" --import "$release_key" >/dev/null 2>&1
key_fingerprint="$(gpg --batch --homedir "$work_dir/gnupg" --with-colons \
    --fingerprint --list-keys | awk -F: '$1 == "fpr" { print $10; exit }')"
if [[ "$key_fingerprint" != "$RELEASE_KEY_FINGERPRINT" ]]; then
    printf 'FFmpeg release key fingerprint mismatch: expected %s, got %s\n' \
        "$RELEASE_KEY_FINGERPRINT" "$key_fingerprint" >&2
    exit 1
fi

gpg --batch --homedir "$work_dir/gnupg" --status-fd 1 \
    --verify "$source_signature" "$source_archive" >"$work_dir/signature-status.txt" 2>&1
verified_fingerprint="$(awk '/^\[GNUPG:\] VALIDSIG / { print $3; exit }' \
    "$work_dir/signature-status.txt")"
if [[ "$verified_fingerprint" != "$RELEASE_KEY_FINGERPRINT" ]]; then
    printf 'FFmpeg archive signature used an unexpected key: %s\n' \
        "$verified_fingerprint" >&2
    exit 1
fi

tar -xf "$source_archive" -C "$work_dir/unpacked"
source_dir="$work_dir/unpacked/ffmpeg-${FFMPEG_VERSION}"
if [[ ! -f "$source_dir/configure" || ! -f "$source_dir/COPYING.LGPLv2.1" ]]; then
    printf 'Pinned FFmpeg source archive is missing configure or COPYING.LGPLv2.1.\n' >&2
    exit 1
fi

configure_args=(
    --prefix="$work_dir/prefix"
    --target-os=mingw32
    --arch=x86_64
    --disable-everything
    --disable-gpl
    --disable-version3
    --disable-nonfree
    --disable-autodetect
    --disable-network
    --enable-shared
    --disable-static
    --enable-w32threads
    --extra-ldflags=-static-libgcc
    --enable-ffmpeg
    --enable-ffprobe
    --enable-avcodec
    --enable-avformat
    --enable-avfilter
    --enable-avutil
    --enable-swresample
    --enable-protocol=file
    --enable-demuxer=mov,mp3,wav,flac,ogg
    --enable-decoder=aac,aac_fixed,alac,mp3,mp3float,ac3,eac3,flac,opus,vorbis,pcm_u8,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_f32le,pcm_f64le
    --enable-filter=silencedetect
    --enable-encoder=pcm_s16le,aac,vorbis,flac
    --enable-muxer=wav,ipod,ogg,flac,null
)

cd "$source_dir"
if ! ./configure "${configure_args[@]}" >"$work_dir/configure.log" 2>&1; then
    cat "$work_dir/configure.log" >&2
    exit 1
fi
if ! make -j"${NUMBER_OF_PROCESSORS:-4}" >"$work_dir/make.log" 2>&1; then
    tail -n 200 "$work_dir/make.log" >&2
    exit 1
fi
if ! make install >"$work_dir/install.log" 2>&1; then
    cat "$work_dir/install.log" >&2
    exit 1
fi

installed_bin="$work_dir/prefix/bin"
if [[ ! -s "$installed_bin/ffmpeg.exe" || ! -s "$installed_bin/ffprobe.exe" ]]; then
    printf 'FFmpeg build did not produce both command-line tools.\n' >&2
    exit 1
fi
shopt -s nullglob
ffmpeg_dlls=("$installed_bin"/*.dll)
if (( ${#ffmpeg_dlls[@]} == 0 )); then
    printf 'FFmpeg shared-library build produced no runtime DLLs.\n' >&2
    exit 1
fi

license_banner="$("$installed_bin/ffmpeg.exe" -L 2>&1)"
if [[ "$license_banner" != *"GNU Lesser General Public"* || \
      "$license_banner" != *"version 2.1 of the License"* ]]; then
    printf 'FFmpeg runtime did not report the expected LGPL 2.1-or-later license.\n' >&2
    printf '%s\n' "$license_banner" >&2
    exit 1
fi
build_configuration="$("$installed_bin/ffmpeg.exe" -buildconf 2>&1)"
for required_flag in --disable-gpl --disable-version3 --disable-nonfree --disable-network; do
    if [[ "$build_configuration" != *"$required_flag"* ]]; then
        printf 'Built FFmpeg configuration is missing required flag %s.\n' "$required_flag" >&2
        exit 1
    fi
done

stage_dir="$work_dir/stage"
cp "$installed_bin/ffmpeg.exe" "$installed_bin/ffprobe.exe" "$stage_dir/"
cp "${ffmpeg_dlls[@]}" "$stage_dir/"

# All FFmpeg libraries are replaceable shared DLLs. GCC helper routines are
# statically linked under GCC's runtime exception; Win32 threads avoid a
# runtime dependency on libwinpthread. Any unexpected non-system import fails.
system32="$(cygpath -u "${WINDIR:-C:\\Windows}")/System32"
for binary in "$stage_dir"/*.exe "$stage_dir"/*.dll; do
    while IFS= read -r imported_dll; do
        imported_lower="${imported_dll,,}"
        [[ "$imported_lower" == api-ms-win-* || "$imported_lower" == ext-ms-win-* ]] && continue
        [[ -f "$stage_dir/$imported_dll" || -f "$system32/$imported_dll" ]] && continue
        printf 'Unexpected external FFmpeg runtime dependency %s imported by %s.\n' \
            "$imported_dll" "$(basename "$binary")" >&2
        printf 'Bundle and license the dependency or remove it from the build.\n' >&2
        exit 1
    done < <(objdump -p "$binary" | awk '/DLL Name:/ { print $3 }')
done

license_package="$(pacman -Qoq "$(cygpath -u "$(gcc -print-file-name=libgcc.a)")")"
license_root="$work_dir/toolchain-licenses"
mkdir -p "$license_root"
license_count=0
while IFS= read -r license_file; do
    [[ -f "$license_file" ]] || continue
    relative="${license_file#/}"
    mkdir -p "$license_root/$(dirname "$relative")"
    cp "$license_file" "$license_root/$relative"
    ((license_count += 1))
done < <(pacman -Ql "$license_package" | awk '$2 ~ /\/share\/licenses\// { print $2 }')
if (( license_count == 0 )); then
    printf 'No license material found for GCC runtime package %s.\n' "$license_package" >&2
    exit 1
fi

mkdir -p "$output_dir"
cp "$source_archive" "$stage_dir/$SOURCE_ARCHIVE_NAME"
cp "$source_signature" "$stage_dir/$SOURCE_ARCHIVE_NAME.asc"
cp "$release_key" "$stage_dir/ffmpeg-release-key.asc"
cp "$source_dir/COPYING.LGPLv2.1" "$stage_dir/FFMPEG-LICENSE-LGPL-2.1.txt"
cp "$script_dir/build_ffmpeg.sh" "$stage_dir/build_ffmpeg.sh"
cp "$script_dir/fetch_ffmpeg.py" "$stage_dir/fetch_ffmpeg.py"
cp -R "$license_root" "$stage_dir/GCC-RUNTIME-LICENSES"

cat >"$stage_dir/FFMPEG-SOURCE-OFFER.md" <<EOF
# FFmpeg corresponding source included with this build

This Windows distribution includes the exact FFmpeg ${FFMPEG_VERSION} source archive,
its detached FFmpeg release signature, the release signing key, the build script,
the source-fetch script, the configure options and generated build metadata.

- Source: ${SOURCE_URL}
- Source archive: ${SOURCE_ARCHIVE_NAME}
- Source SHA-256: ${actual_source_hash}
- Release signer fingerprint: ${verified_fingerprint}

The source is supplied in this distribution under the LGPL 2.1-or-later terms
applicable to this feature-minimal FFmpeg build. The shared FFmpeg libraries are
located beside ffmpeg.exe and ffprobe.exe and can be replaced with compatible
rebuilds. The build disables GPL, version-3-only, nonfree and network components.
EOF

cat >"$stage_dir/FFMPEG-BUILD-METADATA.txt" <<EOF
FFmpeg source-built Windows runtime metadata
============================================
FFmpeg version: ${FFMPEG_VERSION}
Source URL: ${SOURCE_URL}
Source archive: ${SOURCE_ARCHIVE_NAME}
Source archive SHA-256: ${actual_source_hash}
Source signature: ${SOURCE_ARCHIVE_NAME}.asc
Signature result: VALID
Release key fingerprint: ${verified_fingerprint}
Target: x86_64-w64-mingw32 (MSYS2 UCRT64)
GCC version: $(gcc --version | head -n 1)
NASM version: $(nasm --version | head -n 1)
Make version: $(make --version | head -n 1)
GCC runtime package: ${license_package}
FFmpeg license: LGPL 2.1-or-later; GPL/version-3/nonfree components disabled
Network protocols: disabled; local file protocol only
Shared-library policy: FFmpeg DLLs included beside ffmpeg.exe and ffprobe.exe

Configure arguments:
$(printf '  %s\n' "${configure_args[@]}")
Runtime-file SHA-256:
EOF
(cd "$stage_dir" && sha256sum ffmpeg.exe ffprobe.exe ./*.dll) \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'Source SHA-256: %s\n' "$actual_source_hash" >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'Build script SHA-256: %s\n' "$(sha256sum "$stage_dir/build_ffmpeg.sh" | awk '{print $1}')" \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'Source signature SHA-256: %s\n' \
    "$(sha256sum "$stage_dir/$SOURCE_ARCHIVE_NAME.asc" | awk '{print $1}')" \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'Release key SHA-256: %s\n' \
    "$(sha256sum "$stage_dir/ffmpeg-release-key.asc" | awk '{print $1}')" \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'FFmpeg license SHA-256: %s\n' \
    "$(sha256sum "$stage_dir/FFMPEG-LICENSE-LGPL-2.1.txt" | awk '{print $1}')" \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'Source fetcher SHA-256: %s\n' \
    "$(sha256sum "$stage_dir/fetch_ffmpeg.py" | awk '{print $1}')" \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"
printf 'Source offer SHA-256: %s\n' "$(sha256sum "$stage_dir/FFMPEG-SOURCE-OFFER.md" | awk '{print $1}')" \
    >>"$stage_dir/FFMPEG-BUILD-METADATA.txt"

# Replace only known generated FFmpeg outputs in the ignored staging directory.
for stale in "$output_dir/ffmpeg.exe" "$output_dir/ffprobe.exe" \
    "$output_dir"/av*.dll "$output_dir"/sw*.dll \
    "$output_dir"/libav*.dll "$output_dir"/libsw*.dll \
    "$output_dir"/ffmpeg-"$FFMPEG_VERSION".tar.xz \
    "$output_dir"/ffmpeg-"$FFMPEG_VERSION".tar.xz.asc \
    "$output_dir"/ffmpeg-release-key.asc "$output_dir"/FFMPEG-LICENSE-LGPL-2.1.txt \
    "$output_dir"/build_ffmpeg.sh "$output_dir"/fetch_ffmpeg.py \
    "$output_dir"/FFMPEG-SOURCE-OFFER.md "$output_dir"/FFMPEG-BUILD-METADATA.txt; do
    [[ -f "$stale" ]] && rm -f "$stale"
done
for stale in "$output_dir/GCC-RUNTIME-LICENSES"; do
    [[ -d "$stale" ]] && rm -rf "$stale"
done

for staged_file in "$stage_dir"/*; do
    [[ -f "$staged_file" ]] && cp "$staged_file" "$output_dir/"
done
cp -R "$stage_dir/GCC-RUNTIME-LICENSES" "$output_dir/GCC-RUNTIME-LICENSES"
printf 'Built FFmpeg %s from the pinned signed source into %s\n' "$FFMPEG_VERSION" "$output_dir"
