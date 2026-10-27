"""Parser check against synthetic config areas laid out like the real metadata (fake IDs)."""
import importlib.util, pathlib, struct

spec = importlib.util.spec_from_file_location('scan', pathlib.Path(__file__).parent / 'amdraid-scan.py')
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)

A, B, C, D = 0x11, 0x22, 0x33, 0x44


def volume(cfg, off, vid, gen, cols, copies, code, members, size, dtype=scan.RAID10N):
    struct.pack_into('<IIII', cfg, off, scan.VOL_TAG, 0x200, scan.NORMAL, dtype)
    struct.pack_into('<Q', cfg, off + 0x2C, vid)
    struct.pack_into('<Q', cfg, off + 0x50, size)
    struct.pack_into('<Q', cfg, off + 0x60, gen)
    struct.pack_into('<II', cfg, off + 0x6C, cols, copies)
    struct.pack_into('<I', cfg, off + 0x110, code)
    for i, (mid, start, length) in enumerate(members):
        struct.pack_into('<Q24xQQ', cfg, off + 0x200 + 0x40 * i, mid, start, length)


cfg = bytearray(2048 * 512)
half = 3905925120
volume(cfg, 0x580, 7, 4, 2, 1, 1, [(A, 1069056, half), (B, 1069056, half)], 2 * half)    # stale copy
volume(cfg, 0x880, 7, 5, 2, 1, 3, [(A, 1069056, half), (B, 1069056, half)], 2 * half)    # the real one
disks = {A: ('/dev/A', cfg), B: ('/dev/B', cfg), C: ('/dev/C', cfg), D: ('/dev/D', cfg)}
vols = scan.parse_volumes(bytes(cfg))
assert len(vols) == 1 and vols[0]['gen'] == 5, vols                                  # newest generation wins
assert scan.name(vols[0]) == 'RAID0'
assert scan.dm_table(vols[0], disks) == '0 7811850240 striped 2 512 /dev/A 1069056 /dev/B 1069056'
assert scan.dm_table(vols[0], {A: disks[A]}) is None                                 # missing RAID0 member

r1 = bytearray(2048 * 512)
volume(r1, 0, 8, 1, 1, 2, 2, [(A, 2048, 1000), (B, 2048, 1000)], 1000)
v, = scan.parse_volumes(bytes(r1))
assert scan.name(v) == 'RAID1' and v['stripe'] == 256
assert scan.dm_table(v, {B: disks[B]}) == '0 1000 linear /dev/B 2048'                # degraded mirror still reads

r10 = bytearray(2048 * 512)
volume(r10, 0, 9, 1, 2, 2, 0, [(A, 2048, 500), (B, 2048, 500), (C, 2048, 500), (D, 2048, 500)], 1000)
v, = scan.parse_volumes(bytes(r10))
assert scan.name(v) == 'RAID10' and v['stripe'] == 128
assert scan.dm_table(v, disks) == '0 1000 striped 2 128 /dev/A 2048 /dev/C 2048'      # copy 0 of each column

r5 = bytearray(2048 * 512)
volume(r5, 0, 10, 1, 1, 3, 3, [(A, 2048, 51200), (B, 4096, 51200), (C, 2048, 51200)], 102400, scan.RAID5)
v, = scan.parse_volumes(bytes(r5))
assert scan.name(v) == 'RAID5'
assert scan.dm_tables(v, disks, 'x') == [
    ('xm0', '0 51200 linear /dev/A 2048'), ('xm1', '0 51200 linear /dev/B 4096'), ('xm2', '0 51200 linear /dev/C 2048'),
    ('x', '0 102400 raid raid5_ra 2 512 nosync 3 - /dev/mapper/xm0 - /dev/mapper/xm1 - /dev/mapper/xm2')]
assert scan.dm_tables(v, {A: disks[A], C: disks[C]}, 'x')[-1][1].endswith('- /dev/mapper/xm0 - - - /dev/mapper/xm2')
assert scan.dm_tables(v, {A: disks[A]}, 'x') == []                                   # two missing: unreadable
print('ok')
