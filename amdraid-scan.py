#!/usr/bin/env python3
"""Read AMD RAIDXpert (RAIDCore) metadata and print read-only dmsetup commands.

Never writes to any disk. Run as root: sudo python3 -I amdraid-scan.py
Format notes (reverse-engineered 2026-10-25 from one 2x NVMe RAID0):
  disk header  @ LBA 20480: 'RAIDCore' at +0x08, disk id u64 at +0x10,
               config area LBA u64 at +0x20, length (sectors) u32 at +0x28
  config area: 128-byte objects, u32 tag first. 0x25BD = volume:
               +0x04 u32 stripe (sectors, UNCONFIRMED: one sample), +0x50 u64 size,
               +0x60 u32 level (5 = RAID0 seen; 0 = legacy single disk), +0x68 u32 nmembers,
               members at +0x200 + 0x40*i: id u64, data start u64 @+0x20, data len u64 @+0x28
"""
import glob, os, struct, sys

HDR_LBA, SECT = 20480, 512
VOL_TAG, RAID0 = 0x25BD, 5


def read(dev, lba, n):
    fd = os.open(dev, os.O_RDONLY)
    try:
        return os.pread(fd, n * SECT, lba * SECT)
    finally:
        os.close(fd)


def scan_disks():
    disks = {}  # disk id -> (dev, config bytes)
    for dev in sorted(glob.glob('/dev/nvme[0-9]n[0-9]') + glob.glob('/dev/sd[a-z]')):
        try:
            h = read(dev, HDR_LBA, 1)
        except OSError:
            continue
        if h[8:16] != b'RAIDCore':
            continue
        did, cfg_lba, cfg_len = struct.unpack_from('<Q', h, 0x10)[0], *struct.unpack_from('<QI', h, 0x20)
        disks[did] = (dev, read(dev, cfg_lba, cfg_len))
    return disks


def parse_volumes(cfg, disks):
    vols = {}
    for off in range(0, len(cfg) - 0x300, 0x80):
        if struct.unpack_from('<I', cfg, off)[0] != VOL_TAG:
            continue
        stripe = struct.unpack_from('<I', cfg, off + 0x04)[0]
        size, = struct.unpack_from('<Q', cfg, off + 0x50)
        level, n = struct.unpack_from('<I4xI', cfg, off + 0x60)
        if not 2 <= n <= 8 or off + 0x200 + 0x40 * n > len(cfg):
            continue  # legacy single-disk volumes (n=1) need no assembly
        members = []
        for i in range(n):
            m = off + 0x200 + 0x40 * i
            mid, = struct.unpack_from('<Q', cfg, m)
            start, length = struct.unpack_from('<QQ', cfg, m + 0x20)
            members.append((mid, start, length))
        if all(mid in disks for mid, _, _ in members):
            vols[tuple(members)] = (level, stripe, size, members)
    return list(vols.values())  # ponytail: dedupe identical journal copies, newest-wins if they ever differ


def dm_table(level, stripe, size, members, disks):
    if level != RAID0:
        return None
    assert size == sum(l for _, _, l in members), 'member lengths do not add up to volume size'
    devs = ' '.join(f'{disks[mid][0]} {start}' for mid, start, _ in members)
    return f'0 {size} striped {len(members)} {stripe} {devs}'


def main():
    disks = scan_disks()
    print(f'# RAIDCore disks: {", ".join(d for d, _ in disks.values()) or "none"}')
    seen = set()
    for dev, cfg in disks.values():
        for level, stripe, size, members in parse_volumes(cfg, disks):
            t = dm_table(level, stripe, size, members, disks)
            if t in seen:
                continue
            seen.add(t)
            if t is None:
                print(f'# unsupported level {level} with {len(members)} members, skipped')
                continue
            print(f'# RAID0 {len(members)} members, {size * SECT / 1e12:.2f} TB, stripe {stripe * SECT // 1024}K')
            print(f'blockdev --setro {" ".join(disks[m][0] for m, _, _ in members)}')
            print(f'dmsetup create amdraid{len(seen) - 1} --readonly --table "{t}"')


if __name__ == '__main__':
    sys.exit(main())
