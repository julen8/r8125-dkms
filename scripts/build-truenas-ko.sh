#!/usr/bin/env bash
set -euo pipefail

: "${KERNEL_TAG:?KERNEL_TAG must be set}"
: "${GITHUB_SHA:?GITHUB_SHA must be set}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  bc binutils bison build-essential ca-certificates curl dwarves flex gcc-14 \
  git kmod libelf-dev libssl-dev python3 rsync xz-utils zstd bzip2

export ARCH=x86_64
export CC=gcc-14
export HOSTCC=gcc-14
export LOCALVERSION=
export KBUILD_BUILD_USER=truenas-ci
export KBUILD_BUILD_HOST=github-actions

workspace="$PWD"
kernel_dir="$workspace/kernel"
git config --global --add safe.directory "$kernel_dir"
kernel_commit=$(git -C "$kernel_dir" rev-parse HEAD)

# shellcheck source=PKGBUILD
source "$workspace/PKGBUILD"
driver_archive="${_pkgname}-${pkgver}.tar.bz2"
driver_url="${source[0]#*::}"
curl --fail --location --retry 3 "$driver_url" -o "$driver_archive"
printf '%s  %s\n' "${sha256sums[0]}" "$driver_archive" | sha256sum --check -
tar -xjf "$driver_archive"
driver_dir="$workspace/${_pkgname}-${pkgver}/src"
test -f "$driver_dir/Makefile"

cd "$kernel_dir"
config_dir=scripts/package/truenas
for fragment in debian_amd64.config truenas.config tn-production.config; do
  test -s "$config_dir/$fragment"
done
make defconfig
bash scripts/kconfig/merge_config.sh -m .config \
  "$config_dir/debian_amd64.config" \
  "$config_dir/truenas.config" \
  "$config_dir/tn-production.config"
make olddefconfig
grep -qx 'CONFIG_PCI=y' .config
grep -qx 'CONFIG_MODULES=y' .config
make archprepare
mkdir -p debian/certs
cp "$config_dir/debian-uefi-certs.pem" debian/certs/

kernel_release=$(make -s kernelrelease)
make -j"$(nproc)" vmlinux modules
test -s Module.symvers
make -j"$(nproc)" M="$driver_dir" \
  CONFIG_ASPM=n ENABLE_MULTIPLE_TX_QUEUE=y ENABLE_PTP_SUPPORT=y \
  ENABLE_RSS_SUPPORT=y modules

module="$driver_dir/r8125.ko"
test -s "$module"
vermagic=$(modinfo -F vermagic "$module")
if [[ "${vermagic%% *}" != "$kernel_release" ]]; then
  printf 'Kernel release mismatch: %s != %s\n' "$vermagic" "$kernel_release" >&2
  exit 1
fi
readelf -h "$module" | grep -q 'Machine:.*Advanced Micro Devices X86-64'

mkdir -p "$workspace/dist"
artifact="r8125-${pkgver}-${KERNEL_TAG}-${kernel_release}-x86_64.ko"
install -m 0644 "$module" "$workspace/dist/$artifact"
cp .config "$workspace/dist/kernel.config"
{
  printf 'Driver: r8125 %s\n' "$pkgver"
  printf 'Packaging: https://github.com/%s/commit/%s\n' "$GITHUB_REPOSITORY" "$GITHUB_SHA"
  printf 'Kernel tag: %s\nKernel release: %s\n' "$KERNEL_TAG" "$kernel_release"
  printf 'Kernel commit: https://github.com/truenas/linux/commit/%s\n' "$kernel_commit"
  printf 'Compiler: %s\n' "$(gcc-14 --version | head -n 1)"
  printf 'Vermagic: %s\n' "$vermagic"
  printf '\nUnsigned module. The target uname -r must match the kernel release above.\n'
  printf 'Matching vermagic alone does not prove runtime ABI compatibility.\n'
  printf '\n'
  modinfo "$module"
} > "$workspace/dist/build-info.txt"
cd "$workspace/dist"
sha256sum "$artifact" kernel.config build-info.txt > SHA256SUMS