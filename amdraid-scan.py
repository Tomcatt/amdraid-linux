#!/usr/bin/env python3
"""Read AMD RAIDXpert (RAIDCore) metadata and print dmsetup commands (read-only unless --rw).

Never writes to any disk itself. Run as root: sudo python3 -I amdraid-scan.py [--rw]
--rw prints a writable table for RAID0 only: RAID0 has no parity or mirror, so data writes never
need a metadata update, and the table maps only each member's UserDataSpace, so the metadata
region can't be touched. Redundant levels stay read-only (no dirty/resync tracking yet).
USE AT YOUR OWN RISK: unofficial, unaffiliated with AMD, no warranty; the authors are not
responsible for data loss. Back up first and check every printed command before running it.
Format (struct and field names from the DWARF debug info in AMD's rcraid 9.3.3 rcblob.x86_64):
  disk header  @ LBA 20480: 'RAIDCore' at +0x08, disk id u64 at +0x10,
               config area LBA u64 at +0x20, length (sectors) u32 at +0x28
  config area: 128-byte-aligned objects, u32 StructureType first (0x25BC physical, 0x25BD logical)
  RC_LogicalDevice: +0x04 LogicalElementOffset, +0x08 State (0x200 = NORMAL), +0x0C DeviceType,
               +0x2C volume id u64, +0x50 Capacity u64, +0x60 GenerationNumber u64,
               +0x6C FirstCount (columns), +0x70 SecondCount (copies per column),
               +0x110 CacheTagSize = stripe code (3: 256K, 2: 128K, else 64K; per RC_GetStripeStartSector)
  RC_LogicalElement_LE, 0x40 each at LogicalElementOffset, index column*SecondCount + copy:
               +0x00 DeviceID u64, +0x20 UserDataSpace.SectorOffset u64, +0x28 UserDataSpace.Size u64
  DeviceType:  0x1BF5 RAID5/50, 0x1BF6 RAID0/1/10 (RC_RAID10N), 0x1BF7 volume, 0x1BF9 legacy, 0x1BFA RAID6/60
  RAID5 (RC_Raid50LogicalToPhysical, one group): SecondCount disks, row = chunk / (n-1),
               parity on disk row % n, data fills disks in order skipping it = md/dm-raid raid5_ra
Verified on hardware: RAID0 2x NVMe (X870E) and 3x NVMe (X570, BIOS in AHCI mode), 256K. RAID1/10/5 follow the driver's address math and match it
on loop images (full and degraded); none of the three tested on real disks.
"""
import glob, os, struct, sys

HDR_LBA, SECT = 20480, 512
VOL_TAG, RAID5, RAID10N, NORMAL = 0x25BD, 0x1BF5, 0x1BF6, 0x200
STRIPE = {3: 512, 2: 256}  # CacheTagSize code -> sectors; anything else is 128 (64K)


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


def parse_volumes(cfg):
    vols = {}  # volume id -> newest copy in the config log
    for off in range(0, len(cfg) - 0x114, 0x80):
        if struct.unpack_from('<I', cfg, off)[0] != VOL_TAG:
            continue
        elem_off, state, dtype = struct.unpack_from('<III', cfg, off + 0x04)
        vid, = struct.unpack_from('<Q', cfg, off + 0x2C)
        size, = struct.unpack_from('<Q', cfg, off + 0x50)
        gen, = struct.unpack_from('<Q', cfg, off + 0x60)
        cols, copies = struct.unpack_from('<II', cfg, off + 0x6C)
        code, = struct.unpack_from('<I', cfg, off + 0x110)
        n = cols * copies
        if not 1 <= n <= 16 or off + elem_off + 0x40 * n > len(cfg):
            continue
        members = []
        for i in range(n):
            m = off + elem_off + 0x40 * i
            mid, = struct.unpack_from('<Q', cfg, m)
            start, length = struct.unpack_from('<QQ', cfg, m + 0x20)
            members.append((mid, start, length))
        if vid not in vols or gen > vols[vid]['gen']:
            vols[vid] = dict(gen=gen, state=state, dtype=dtype, cols=cols, copies=copies,
                             stripe=STRIPE.get(code, 128), size=size, members=members)
    return list(vols.values())


def name(v):
    if v['dtype'] == RAID5 and v['cols'] == 1:
        return 'RAID5'
    if v['dtype'] != RAID10N:
        return f'type 0x{v["dtype"]:X}'
    return 'RAID0' if v['copies'] == 1 else 'RAID1' if v['cols'] == 1 else 'RAID10'


def raid5_tables(v, disks, dm):
    """One linear map per member (dm-raid has no per-device offset), then raid5_ra over them."""
    n, members = v['copies'], v['members']
    if v['size'] % (n - 1) or sum(m not in disks for m, _, _ in members) > 1:
        return []  # RAID5 reads with at most one member missing
    per = v['size'] // (n - 1)
    out, devs = [], []
    for i, (mid, start, length) in enumerate(members):
        if mid not in disks:
            devs.append('- -')
            continue
        assert per <= length, 'member smaller than volume needs'
        out.append((f'{dm}m{i}', f'0 {per} linear {disks[mid][0]} {start}'))
        devs.append(f'- /dev/mapper/{dm}m{i}')
    return out + [(dm, f'0 {v["size"]} raid raid5_ra 2 {v["stripe"]} nosync {n} {" ".join(devs)}')]


def dm_tables(v, disks, dm='amdraid0'):
    """[(dm name, table)] to create in order, all read-only; [] if unsupported or incomplete."""
    if v['dtype'] == RAID5 and v['cols'] == 1 and v['copies'] >= 3:
        return raid5_tables(v, disks, dm)
    t = dm_table(v, disks)
    return [(dm, t)] if t else []


def dm_table(v, disks):
    """RAID0/1/10 table using the first present copy of each column; None if unsupported or incomplete."""
    if v['dtype'] != RAID10N or (v['copies'] == 1 and v['cols'] == 1):
        return None  # RAID50/6/60 undecoded; 1x1 is a legacy passthrough disk, needs no assembly
    cols = [v['members'][c * v['copies']:(c + 1) * v['copies']] for c in range(v['cols'])]
    picks = [next((m for m in col if m[0] in disks), None) for col in cols]
    if None in picks:
        return None
    assert v['size'] == sum(l for _, _, l in picks), 'member lengths do not add up to volume size'
    if len(picks) == 1:
        mid, start, _ = picks[0]
        return f'0 {v["size"]} linear {disks[mid][0]} {start}'
    devs = ' '.join(f'{disks[mid][0]} {start}' for mid, start, _ in picks)
    return f'0 {v["size"]} striped {len(picks)} {v["stripe"]} {devs}'


def commands(v, disks, dm, rw=False):
    """Comment + shell lines to assemble one volume; [] if it can't be assembled."""
    tables = dm_tables(v, disks, dm)
    if not tables:
        return [f'# {name(v)} {v["cols"]}x{v["copies"]}: unsupported or members missing, skipped'] \
            if v['cols'] * v['copies'] > 1 else []
    warn = '' if v['state'] == NORMAL else f'  WARNING: state 0x{v["state"]:X}, not NORMAL'
    out = [f'# {name(v)} {v["cols"]}x{v["copies"]}, {v["size"] * SECT / 1e12:.2f} TB, '
           f'stripe {v["stripe"] * SECT // 1024}K{warn}']
    if rw and (name(v) != 'RAID0' or warn):
        out.append('# --rw refused: RAID0 in NORMAL state only; read-only instead')
        rw = False
    devs = ' '.join(disks[m][0] for m, _, _ in v['members'] if m in disks)
    out.append(f'blockdev --setrw {devs}' if rw else f'blockdev --setro {devs}')
    out += [f'dmsetup create {d}{"" if rw else " --readonly"} --table "{t}"' for d, t in tables]
    return out


def main():
    rw = '--rw' in sys.argv[1:]
    disks = scan_disks()
    print('# Use at your own risk: no warranty, authors not responsible for data loss. Review before running.')
    print(f'# RAIDCore disks: {", ".join(d for d, _ in disks.values()) or "none"}')
    vols = {}
    for _, cfg in disks.values():  # every member carries a copy of the log; keep the newest per volume
        for v in parse_volumes(cfg):
            key = tuple(m for m, _, _ in v['members'])
            if key not in vols or v['gen'] > vols[key]['gen']:
                vols[key] = v
    for i, v in enumerate(vols.values()):
        print('\n'.join(commands(v, disks, f'amdraid{i}', rw)))


if __name__ == '__main__':
    sys.exit(main())
