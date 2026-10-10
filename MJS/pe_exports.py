# -*- coding: utf-8 -*-
"""解析 PE 导出表，列出 DLL 导出的函数"""
import struct, sys

def parse_exports(path, keyword=None):
    data = open(path, 'rb').read()
    # DOS header
    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    assert data[e_lfanew:e_lfanew+4] == b'PE\x00\x00'
    # COFF header
    opt_off = e_lfanew + 4 + 20
    magic = struct.unpack_from('<H', data, opt_off)[0]
    is_pe32plus = (magic == 0x20B)
    if is_pe32plus:
        dd_off = opt_off + 112
    else:
        dd_off = opt_off + 96
    # Export directory (index 0)
    exp_rva, exp_size = struct.unpack_from('<II', data, dd_off)
    if exp_rva == 0:
        print('无导出表'); return []
    # section headers
    nsec = struct.unpack_from('<H', data, e_lfanew + 4 + 2)[0]
    sec_off = opt_off + (112 if is_pe32plus else 96) + 128  # 简化：section table 在 optional header 后
    # 更准确：optional header size
    opt_size = struct.unpack_from('<H', data, e_lfanew + 4 + 16)[0]
    sec_off = e_lfanew + 4 + 20 + opt_size
    sections = []
    for i in range(nsec):
        off = sec_off + i * 40
        name = data[off:off+8].rstrip(b'\x00').decode('ascii', 'ignore')
        vsize, vaddr, rsize, roff = struct.unpack_from('<IIII', data, off+8)
        sections.append((name, vaddr, vsize, roff, rsize))
    def rva2off(rva):
        for name, vaddr, vsize, roff, rsize in sections:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return roff + (rva - vaddr)
        return None
    # export dir
    eoff = rva2off(exp_rva)
    nfuncs, nnames = struct.unpack_from('<II', data, eoff + 20)
    addr_of_funcs, addr_of_names, addr_of_ordinals = struct.unpack_from('<III', data, eoff + 28)
    names_off = rva2off(addr_of_names)
    funcs_off = rva2off(addr_of_funcs)
    names = []
    for i in range(nnames):
        nrva = struct.unpack_from('<I', data, names_off + i*4)[0]
        noff = rva2off(nrva)
        end = data.index(b'\x00', noff)
        names.append(data[noff:end].decode('ascii', 'ignore'))
    return names

if __name__ == '__main__':
    path = sys.argv[1]
    names = parse_exports(path)
    print(f'导出 {len(names)} 个函数')
    kw = sys.argv[2] if len(sys.argv) > 2 else None
    for n in names:
        if kw is None or kw.lower() in n.lower():
            print(' ', n)
