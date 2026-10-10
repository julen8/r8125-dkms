#!/usr/bin/env bash
set -euo pipefail

: "${TRUENAS_VERSION:?TRUENAS_VERSION must be set}"
: "${GITHUB_SHA:?GITHUB_SHA must be set}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"

workspace="$PWD"
if [[ "${INSTALL_BUILD_DEPS:-true}" == true ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends python3
fi
mapfile -t target < <(python3 - "$workspace/scripts/truenas-targets.json" "$TRUENAS_VERSION" <<'PY'
import json
import sys

with open(sys.argv[1]) as manifest:
    target = json.load(manifest)[sys.argv[2]]
for field in ("update_url", "update_sha256", "kernel_release", "compiler"):
    print(target[field])
PY
)
[[ ${#target[@]} == 4 ]]
update_url=${target[0]}
update_sha256=${target[1]}
expected_release=${target[2]}
compiler=${target[3]}
[[ "$update_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ "$compiler" =~ ^gcc-[0-9]+$ ]]

if [[ "${INSTALL_BUILD_DEPS:-true}" == true ]]; then
  apt-get install -y --no-install-recommends \
    binutils build-essential ca-certificates curl "$compiler" kmod libelf-dev \
    python3 squashfs-tools xz-utils bzip2
fi

build_dir="$workspace/.build/truenas-$TRUENAS_VERSION"
mkdir -p "$build_dir"
cd "$build_dir"
if ! printf '%s  update.squashfs\n' "$update_sha256" | sha256sum --check --status; then
  curl --fail --location --retry 3 "$update_url" -o update.squashfs
fi
printf '%s  update.squashfs\n' "$update_sha256" | sha256sum --check -
unsquashfs -no-progress -processors 2 -d outer -f update.squashfs rootfs.squashfs
unsquashfs -no-progress -processors 2 -d rootfs -f outer/rootfs.squashfs \
  usr/src/linux-headers-truenas-production-amd64 "boot/config-$expected_release"
headers_dir="$build_dir/rootfs/usr/src/linux-headers-truenas-production-amd64"
kernel_config="$build_dir/rootfs/boot/config-$expected_release"
kernel_release=$(cat "$headers_dir/include/config/kernel.release")
[[ "$kernel_release" == "$expected_release" ]]
test -s "$headers_dir/Module.symvers"
test -s "$headers_dir/include/generated/autoconf.h"
test -x "$headers_dir/scripts/mod/modpost"
grep -qx 'CONFIG_PCI=y' "$kernel_config"
grep -qx 'CONFIG_MODULES=y' "$kernel_config"
grep -qx 'CONFIG_MODVERSIONS=y' "$kernel_config"
grep -Eq "^CONFIG_GCC_VERSION=${compiler#gcc-}[0-9]{4}$" "$kernel_config"
compiler_version=$("$compiler" -dumpversion)
[[ "${compiler_version%%.*}" == "${compiler#gcc-}" ]]
symvers_sha256=$(sha256sum "$headers_dir/Module.symvers" | awk '{print $1}')

export ARCH=x86_64
export CC="$compiler"
export HOSTCC="$compiler"
unset LOCALVERSION KBUILD_OUTPUT KBUILD_EXTMOD

# shellcheck source=PKGBUILD
source "$workspace/PKGBUILD"
driver_archive="${_pkgname}-${pkgver}.tar.bz2"
driver_url="${source[0]#*::}"
curl --fail --location --retry 3 "$driver_url" -o "$driver_archive"
printf '%s  %s\n' "${sha256sums[0]}" "$driver_archive" | sha256sum --check -
tar -xjf "$driver_archive"
driver_dir="$build_dir/${_pkgname}-${pkgver}/src"
test -f "$driver_dir/Makefile"
make -C "$headers_dir" -j"$(nproc)" M="$driver_dir" \
  CONFIG_ASPM=n ENABLE_MULTIPLE_TX_QUEUE=y ENABLE_PTP_SUPPORT=y \
  ENABLE_RSS_SUPPORT=y modules

module="$driver_dir/r8125.ko"
test -s "$module"
vermagic=$(modinfo -F vermagic "$module")
[[ "${vermagic%% *}" == "$kernel_release" ]]
readelf -h "$module" | grep 'Machine:.*Advanced Micro Devices X86-64'
modprobe --show-modversions "$module" > module-versions.txt
test -s module-versions.txt
awk '
  NR == FNR { crc[$2] = tolower($1); next }
  {
    count++
    if (!($2 in crc) || tolower($1) != crc[$2]) {
      print "Symbol CRC mismatch:", $2, $1, crc[$2] > "/dev/stderr"
      failed = 1
    }
  }
  END { if (!count || failed) exit 1; print "Verified symbol CRCs:", count }
' "$headers_dir/Module.symvers" module-versions.txt
[[ "$(sha256sum "$headers_dir/Module.symvers" | awk '{print $1}')" == "$symvers_sha256" ]]

dist_dir="$workspace/dist/$TRUENAS_VERSION"
mkdir -p "$dist_dir"
artifact="r8125-${pkgver}-TrueNAS-${TRUENAS_VERSION}-${kernel_release}-x86_64"
install -m 0644 "$module" "$dist_dir/$artifact.ko"
install -m 0644 "$kernel_config" "$dist_dir/$artifact.config"
{
  printf 'Driver: r8125 %s\n' "$pkgver"
  printf 'Packaging: https://github.com/%s/commit/%s\n' "$GITHUB_REPOSITORY" "$GITHUB_SHA"
  printf 'TrueNAS: %s\nKernel release: %s\n' "$TRUENAS_VERSION" "$kernel_release"
  printf 'Update: %s\nUpdate SHA256: %s\n' "$update_url" "$update_sha256"
  printf 'Module.symvers SHA256: %s\n' "$symvers_sha256"
  printf 'Compiler: %s\n' "$("$compiler" --version | head -n 1)"
  cat "$headers_dir/include/generated/compile.h"
  printf 'Options: CONFIG_ASPM=n ENABLE_MULTIPLE_TX_QUEUE=y ENABLE_PTP_SUPPORT=y ENABLE_RSS_SUPPORT=y\n'
  printf 'Vermagic: %s\n' "$vermagic"
  printf '\nUnsigned module. The target uname -r must match the kernel release above.\n'
  printf 'Matching vermagic alone does not prove runtime ABI compatibility.\n'
  printf '\n'
  modinfo "$module"
} > "$dist_dir/$artifact.txt"
cd "$dist_dir"
sha256sum "$artifact.ko" "$artifact.config" "$artifact.txt" > "$artifact.SHA256SUMS"