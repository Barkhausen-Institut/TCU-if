from elftools.elf.elffile import ELFFile

import difflib

def bindiff(bin1, bin2):
    assert len(bin1) == len(bin2)
    for i in range(0, len(bin1), 16):
        r1 = bin1[i:i + 16]
        r2 = bin2[i:i + 16]
        if r1 != r2:
            print("{:#x}: {} vs. {}".format(i, r1.hex(), r2.hex()))

class Memory(object):
    """
    represents a memory module on the chip
    """
    def __init__(self, nocif, nocid, offset=0, ispe=False):
        self.nocif = nocif
        self.nocid = nocid
        self.ispe = ispe
        self.offset = offset

    def read_word(self, addr):
        """
        read a single 64-bit integer from memory at given address
        """
        return self.read_words(addr, 1)[0]

    def read_words(self, addr, count):
        """
        read <count> 64-bit integers from memory at given address
        """
        data = self.read_bytes(addr, count * 8)
        res = []
        for off in range(0, count * 8, 8):
            res.append(int.from_bytes(data[off:off + 8], byteorder='little'))
        return res

    def read_bytes(self, addr, len):
        """
        read bytes from memory at given address
        """
        assert isinstance(addr, int), "address must be an integer"
        return self.nocif.read_bytes(self.nocid, addr + self.offset, len)

    def write_word(self, addr, word):
        """
        writes a 64-bit integer into memory at given address
        """
        return self.write_words(addr, [word], False)

    def write_words(self, addr, words, burst=True):
        """
        writes a list of 64-bit integers into memory at given address
        """
        assert isinstance(words, list), "words must be a list of integers"
        data = bytearray()
        for word in words:
            assert isinstance(word, int), "words must be a list of integers"
            data += word.to_bytes(8, byteorder='little')
        return self.write_bytes(addr, bytes(data), burst)

    def write_elf(self, file, off=0):
        """
        Writes the LOAD segments of the given ELF binary into memory
        """
        with open(file, 'rb') as f:
            elf = ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type'] != 'PT_LOAD':
                    continue

                if seg['p_filesz'] > 0:
                    addr = seg['p_vaddr'] + off
                    print("Loading {} bytes at {:#x}".format(seg['p_filesz'], addr))
                    burst = addr % 16 == 0
                    self.write_bytes_checked(seg['p_vaddr'] + off, seg.data(), burst)

                zero_num = seg['p_memsz'] - seg['p_filesz']
                if zero_num > 0:
                    addr = seg['p_vaddr'] + seg['p_filesz'] + off
                    print("Zeroing {} bytes at {:#x}".format(zero_num, addr))
                    burst = addr % 16 == 0
                    self.write_bytes_checked(addr, bytes([0] * zero_num), burst)

    def write_bytes(self, addr, data, burst=True):
        """
        write bytes into memory at given address
        """
        assert isinstance(addr, int), "address must be an integer"
        assert isinstance(data, bytes), "data must be a byte-like object"
        return self.nocif.write_bytes(self.nocid, self.offset + addr, data, burst)

    def write_bytes_checked(self, addr, data, burst=True):
        """
        writes bytes into memory at given address and checks whether the data has been written
        correctly by reading it afterwards.
        """
        # write+read in chunks of 1MB to on the one hand limit the amount of data we have to
        # retransmit in case of errors and on the other hand get reasonable speed by not-too-small
        # chunks.
        off = 0
        while off < len(data):
            # try a few times to write that chunk to memory until we give up
            for i in range(0, 3):
                try:
                    amount = min(1024 * 1024, len(data) - off)
                    self.write_bytes(addr + off, data[off:off + amount], burst)
                    written = self.read_bytes(addr + off, amount)
                    if written == data[off:off + amount]:
                        break
                except:
                    continue
            if i == 2:
                assert False, "Unable to write bytes to {:#x}; giving up after 3 attempts".format(addr)
            off += amount

    def __repr__(self):
        return '<Memory Module:%d:%d>' % self.nocid

    def __setitem__(self, idx, val):
        if isinstance(idx, slice):
            assert idx.step == None, "Slice stepping not supported!"
            assert idx.start % 8 == 0 and idx.stop % 8 == 0, \
                "range is not 8-byte aligned: 0x%x:0x%x" % (idx.start. idx.stop)
            size = (idx.stop - idx.start) / 8
            if isinstance(val, int):
                val = [val] * size
            assert isinstance(val, list)
            assert len(val) == size
            self.write_words(idx.start, val)
        elif isinstance(idx, int):
            assert isinstance(val, int)
            self.write_word(idx, val)
        else:
            assert False, "setitem: index type:%s (%s)" % (type(idx), idx)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            assert idx.step == None, "Slice stepping not supported!"
            assert idx.start % 8 == 0 and idx.stop % 8 == 0, \
                "range is not 8-byte aligned: 0x%x:0x%x" % (idx.start, idx.stop)
            size = (idx.stop - idx.start) / 8
            return self.read_words(idx.start, size)
        elif isinstance(idx, int):
            assert idx % 8 == 0, "index must be 8-byte aligned 0x%x" % idx
            return self.read_word(idx)
        else:
            assert False, "getitem: index type: %s (%s)" % (type(idx), idx)
