# amdraid-linux

Read AMD RAIDXpert (BIOS RAID, RAIDCore-based) RAID0/1/10/5 arrays on Linux without AMD's abandoned `rcraid` driver.
`amdraid-scan.py` parses the on-disk metadata and prints a **read-only** device-mapper table.

```
sudo python3 -I amdraid-scan.py      # prints commands, runs nothing
python3 -I test_scan.py              # parser check against a synthetic config area
```

**Status: experimental, read-only.** Verified on two boards; on both the reassembled volume
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

Never mount the result read-write; Windows Fast Startup leaves NTFS in a hibernated state.

## Disclaimer

**Use at your own risk.** This is unofficial, reverse-engineered software with no affiliation
with AMD. It is provided "as is", without warranty of any kind. The authors are not responsible
for any data loss, corruption, or damage resulting from its use. Back up anything you care about
before touching RAID member disks, and verify every command it prints before running it.
