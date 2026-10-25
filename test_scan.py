"""Parser check against a synthetic config area laid out like a real 2x NVMe RAID0 (fake IDs)."""
import importlib.util, pathlib, struct

spec = importlib.util.spec_from_file_location('scan', pathlib.Path(__file__).parent / 'amdraid-scan.py')
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)

A, B = 0x1111111111111111, 0x2222222222222222
cfg = bytearray(2048 * 512)
vol = 0x580  # 128-byte aligned, as in the real log
struct.pack_into('<II', cfg, vol, scan.VOL_TAG, 512)                   # tag, stripe (sectors)
struct.pack_into('<Q', cfg, vol + 0x50, 7811850240)                    # volume size
struct.pack_into('<I4xI', cfg, vol + 0x60, scan.RAID0, 2)              # level, member count
for i, mid in enumerate((A, B)):
    struct.pack_into('<Q24xQQ', cfg, vol + 0x200 + 0x40 * i, mid, 1069056, 3905925120)

disks = {A: ('/dev/A', cfg), B: ('/dev/B', cfg)}
vols = scan.parse_volumes(bytes(cfg), disks)
assert len(vols) == 1, vols
assert scan.dm_table(*vols[0], disks) == '0 7811850240 striped 2 512 /dev/A 1069056 /dev/B 1069056'
assert scan.parse_volumes(bytes(cfg), {A: disks[A]}) == []             # missing member -> not assembled
print('ok')
