# amdraid-linux

Read AMD RAIDXpert (BIOS RAID, RAIDCore-based) RAID0/1/10/5 arrays on Linux without AMD's abandoned `rcraid` driver.
`amdraid-scan.py` parses the on-disk metadata and prints a device-mapper table: read-only by default,
writable with `--rw` for RAID0 only.

```
sudo python3 -I amdraid-scan.py      # prints commands, runs nothing
sudo python3 -I amdraid-scan.py --rw # RAID0: writable table; other levels fall back to read-only
python3 -I test_scan.py              # parser check against a synthetic config area
```

**Status: experimental.** Verified on two boards; on both the reassembled volume
mounts read-only and file CRCs check out:

| Board (chipset) | Array |
|---|---|
| MSI MEG X870E GODLIKE (X870E) | RAID0, 2x NVMe, 256K stripe |
| Gigabyte X570 AORUS XTREME (X570) | RAID0, 3x NVMe (mixed models), 256K stripe |

The X570 array was read with the BIOS switched back to AHCI, so the members only need to be
visible as plain disks. AMD's driver lists Bolton, Bristol, Promontory and Summit platforms, so
other AM4/AM5 boards are likely the same format; reports welcome.

Format notes are in the docstring of `amdraid-scan.py`; field names come from the DWARF
debug info AMD shipped in the rcraid 9.3.3 driver blob. RAID1, RAID10 and RAID5
(right-asymmetric parity, assembled with dm-raid `raid5_ra`) were checked against loop-device
images encoded from the driver's own address math, including degraded arrays with a member
missing. None of the three has been tested on real disks yet. RAID50/6/60 and
spanned volumes are detected but not assembled.

## Writing (RAID0 only)

RAID0 keeps no parity or mirror, so writing data never requires a metadata update, and the
`--rw` table maps only each member's data area, leaving the metadata region unmapped. Redundant
levels stay read-only until dirty/resync tracking exists: a Linux write the BIOS doesn't know
about could leave mirrors or parity out of sync.

Tested end to end on the X570 array: with `--rw`, a 4 GiB file written through NTFS read back
identical after tearing down and reassembling read-only from a fresh scan (read with a second
NTFS driver). Existing files were unchanged, and so was everything outside the mapped data areas
on every member, metadata included.

The filesystem is a separate problem. Windows Fast Startup leaves NTFS hibernated with a dirty
journal, which ntfs-3g refuses to mount read-write. The test used the kernel's `ntfs3 -o force`
(it replays the journal) and then deleted `hiberfil.sys`, since Windows must never resume a
hibernation image older than your writes. Only do this when you don't need what was open in Windows.

The 64 KiB just before the RAIDCore header (sectors 20352-20479) is not stable. On the X570 board,
something early in every boot (probably firmware) rewrites it on the first member with what looks
like leftover RAM. The scanner never reads it and it lies outside the data area, but don't treat it
as invariant when comparing disks before and after.

## Disclaimer

**Use at your own risk.** This is unofficial, reverse-engineered software with no affiliation
with AMD. It is provided "as is", without warranty of any kind. The authors are not responsible
for any data loss, corruption, or damage resulting from its use. Back up anything you care about
before touching RAID member disks, and verify every command it prints before running it.
