# amdraid-linux

Read AMD RAIDXpert (BIOS RAID, RAIDCore-based) RAID0/1/10/5 arrays on Linux without AMD's abandoned `rcraid` driver.
`amdraid-scan.py` parses the on-disk metadata and prints a **read-only** device-mapper table.

```
sudo python3 -I amdraid-scan.py      # prints commands, runs nothing
python3 -I test_scan.py              # parser check against a synthetic config area
```

**Status: experimental, read-only.** Verified on one array (2x NVMe RAID0, 256K stripe):
the reassembled volume mounts and file CRCs check out.

Format notes are in the docstring of `amdraid-scan.py`; field names come from the DWARF
debug info AMD shipped in the rcraid 9.3.3 driver blob. RAID1/RAID10 tables follow from the
driver code but are untested on real disks. RAID5 (right-asymmetric parity, assembled with
dm-raid `raid5_ra`, reads degraded with one member missing) was checked against loop-device
images encoded from the driver's address math, also not yet on real disks. RAID50/6/60 and
spanned volumes are detected but not assembled.

Never mount the result read-write; Windows Fast Startup leaves NTFS in a hibernated state.

## Disclaimer

**Use at your own risk.** This is unofficial, reverse-engineered software with no affiliation
with AMD. It is provided "as is", without warranty of any kind. The authors are not responsible
for any data loss, corruption, or damage resulting from its use. Back up anything you care about
before touching RAID member disks, and verify every command it prints before running it.
