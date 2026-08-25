#!/usr/bin/env bash
#
# Grow the root filesystem into space the disk already has.
#
#   sudo bash infra/extend-disk.sh            # look, change nothing
#   sudo bash infra/extend-disk.sh --apply    # grow it
#
# **It reports before it acts, and that is not politeness.** "Extend the disk"
# describes at least four different situations, and the command that fixes one
# destroys another:
#
#   1. The provider grew the virtual disk and the partition never followed.
#      This is the common one and the only one this script handles: the
#      partition grows into free space that is already there, and the
#      filesystem grows into the partition. Both are online operations and
#      neither moves data.
#   2. The partition is already full-size and the *volume* is what needs
#      growing. That is a control-panel operation at the provider, not
#      something any command on the machine can do.
#   3. There is a second, unmounted disk. Growing root does nothing; the disk
#      needs partitioning, formatting and mounting, and where it should be
#      mounted is a decision - Postgres data, Docker images and backups all
#      want it for different reasons.
#   4. The disk is fine and something is simply using it. `docker system prune`
#      recovers more than a resize would, instantly, and the build cache is
#      usually most of it.
#
# So the default run prints the layout and says which of the four it looks
# like. Nothing is guessed, because a wrong guess here is a filesystem.

set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

say() { printf '\n== %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

say "filesystems"
df -hT -x tmpfs -x devtmpfs

say "block devices"
lsblk -o NAME,SIZE,FSTYPE,TYPE,MOUNTPOINT

ROOT_SOURCE="$(findmnt -no SOURCE /)"
echo ""
echo "root is on: ${ROOT_SOURCE}"

# LVM and a plain partition need different commands, and everything below
# depends on telling them apart. `lsblk` names the type of the device itself,
# which is the direct answer - inferring it from the device path means parsing
# names like /dev/mapper/ubuntu--vg-ubuntu--lv, where the doubled hyphens are
# an escape rather than part of the volume group's name.
if lsblk -no TYPE "$ROOT_SOURCE" 2>/dev/null | grep -qx lvm; then
  LAYOUT="lvm"
else
  LAYOUT="partition"
fi
echo "layout:     ${LAYOUT}"

say "unused space on the disks"
if command -v parted >/dev/null 2>&1; then
  for disk in $(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}'); do
    free="$(parted -s "/dev/${disk}" unit GiB print free 2>/dev/null | grep -i 'free space' | tail -1 || true)"
    if [ -n "$free" ]; then
      echo "/dev/${disk}: ${free}"
    else
      echo "/dev/${disk}: no free space reported"
    fi
  done
else
  echo "(parted is not installed, so free space cannot be measured here)"
  echo "  apt-get install -y parted"
fi

say "what docker is holding"
docker system df 2>/dev/null || echo "(docker not running or not installed)"

if [ "$APPLY" -ne 1 ]; then
  cat <<'ADVICE'

Nothing was changed. Read the three sections above, then:

  * Free space on the disk and a root partition smaller than it
      -> re-run with --apply. The partition and filesystem grow into it.

  * No free space, and the volume is the size you were billed for
      -> the disk itself has to be grown at the provider first. Nothing on
         this machine can do that. Grow it there, then re-run with --apply.

  * A second disk with no mountpoint
      -> that is a different job and this script will not guess at it. Where
         it belongs depends on what is filling up: the database, the Docker
         images, or the backups.

  * Docker holding several gigabytes of build cache
      -> `docker system prune -af --volumes` recovers it now, without a
         resize. Read what it lists before agreeing: --volumes removes
         unused volumes, and "unused" includes a database volume whose
         container happens to be stopped.

ADVICE
  exit 0
fi

say "growing"
DISK="/dev/$(lsblk -no PKNAME "$ROOT_SOURCE" | head -1)"
PART_NUM="$(basename "$ROOT_SOURCE" | grep -oE '[0-9]+$' || true)"

if [ "$LAYOUT" = "lvm" ]; then
  echo "-> LVM: extending the logical volume into free extents"
  lvextend -r -l +100%FREE "$ROOT_SOURCE"
else
  [ -n "$PART_NUM" ] || { echo "cannot tell which partition number ${ROOT_SOURCE} is" >&2; exit 1; }
  echo "-> growing partition ${PART_NUM} on ${DISK}"
  # growpart exits 1 with NOCHANGE when there is nothing to do. That is not a
  # failure and must not stop the resize below, which may still be needed.
  growpart "$DISK" "$PART_NUM" || echo "   (partition already at full size)"
  echo "-> growing the filesystem"
  case "$(findmnt -no FSTYPE /)" in
    ext2|ext3|ext4) resize2fs "$ROOT_SOURCE" ;;
    xfs)            xfs_growfs / ;;
    btrfs)          btrfs filesystem resize max / ;;
    *)              echo "unhandled filesystem: $(findmnt -no FSTYPE /)" >&2; exit 1 ;;
  esac
fi

say "after"
df -hT /
