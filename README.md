# amdraid-linux

Read AMD RAIDXpert (BIOS RAID, RAIDCore-based) arrays on Linux without AMD's abandoned `rcraid` driver.
`amdraid-scan.py` parses the on-disk metadata and prints a **read-only** device-mapper table.

```
sudo python3 -I amdraid-scan.py      # prints commands, runs nothing
python3 -I test_scan.py              # parser check against a synthetic config area
```

**Status: experimental, read-only.** Verified on one array (2x NVMe RAID0, 256K stripe):
the reassembled volume mounts and file CRCs check out.

Format notes are in the docstring of `amdraid-scan.py`. Open questions:
- the stripe field (+0x04 = 0x200) is unconfirmed; 512 is also the sector size
- only RAID0 (level 5) is decoded; RAID1/5/10 level codes are unknown

Never mount the result read-write; Windows Fast Startup leaves NTFS in a hibernated state.
