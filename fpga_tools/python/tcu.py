from enum import Enum
import modids


def modid_to_tile(modid):
    try:
        return modids.MODID_TO_TILE[modid]
    except:
        return "Unknown({:#x})".format(modid)

class Flags():
    READ = 1
    WRITE = 2
    RDWR = 3
    FIXED = 4

    def flags_bits2str(flag_bits):
        flag_str = ""
        if flag_bits & Flags.FIXED:
            flag_str += "F"
        if flag_bits & Flags.WRITE:
            flag_str += "W"
        if flag_bits & Flags.READ:
            flag_str += "R"
        return flag_str


class EP():
    INVALID = 0
    SEND = 1
    RECEIVE = 2
    MEMORY = 3

    def invalid():
        return EP(0, [EP.INVALID, 0, 0, 0])

    def from_regs(regs):
        ep = EP(0, regs)
        if ep.type() == EP.SEND:
            return SendEP(regs)
        if ep.type() == EP.RECEIVE:
            return RecvEP(regs)
        if ep.type() == EP.MEMORY:
            return MemEP(regs)
        return ep

    def __init__(self, version, regs):
        self.version = version
        self.regs = regs

    def type(self):
        return self.regs[0] & 0x7

    def act(self):
        return (self.regs[0] >> 3) & 0xFFFF
    def set_act(self, act):
        self.regs[0] &= ~(0xFFFF << 3)
        self.regs[0] |= (act & 0xFFFF) << 3;

    def dynamic(self):
        return (self.regs[0] >> 62) & 0x1

    def frozen(self):
        return (self.regs[0] >> 63) & 0x1

    def __repr__(self):
        return "Inv [type={}, act={}, dynamic={}, frozen={}]".format(
            self.type(), self.act(), self.dynamic(), self.frozen()
        )

class MemEP(EP):
    def __init__(self, version = 0, regs = [EP.MEMORY, 0, 0, 0]):
        super(MemEP, self).__init__(version, regs)

    def tile(self):
        return (self.regs[0] >> 23) & 0xFF
    def set_tile(self, tile):
        self.regs[0] &= ~(0xFF << 23)
        self.regs[0] |= (tile & 0xFF) << 23;

    def chip(self):
        return (self.regs[0] >> 31) & 0x3F
    def set_chip(self, chip):
        self.regs[0] &= ~(0x3F << 31)
        self.regs[0] |= (chip & 0x3F) << 31;

    def gen(self):
        return (self.regs[0] >> 37) & 0xFF

    def dynamic(self):
        return (self.regs[0] >> 62) & 0x1

    def frozen(self):
        return (self.regs[0] >> 63) & 0x1

    def addr(self):
        return self.regs[1]
    def set_addr(self, addr):
        self.regs[1] = addr

    def size(self):
        return self.regs[2]
    def set_size(self, size):
        self.regs[2] = size

    def flags(self):
        return Flags.flags_bits2str((self.regs[0] >> 19) & 0xF)
    def set_flags(self, flags):
        self.regs[0] &= ~(0xF << 19)
        self.regs[0] |= (flags & 0xF) << 19

    def __repr__(self):
        return "Mem [chip={}, tile={}, act={:#x}, gen={}, dynamic={}, frozen={}, addr={:#x}, size={:#x}, flags={}]".format(
            self.chip(), modid_to_tile(self.tile()), self.act(), self.gen(), self.dynamic(), self.frozen(), self.addr(),
            self.size(), self.flags()
        )

class SendEP(EP):
    UNLIMITED_CRD = 0x3F

    def __init__(self, version, regs = [EP.SEND, 0, 0, 0]):
        super(SendEP, self).__init__(version, regs)

    def tile(self):
        return (self.regs[1] >> 16) & 0xFF
    def set_tile(self, tile):
        self.regs[1] &= ~(0xFF << 16)
        self.regs[1] |= (tile & 0xFF) << 16

    def chip(self):
        return (self.regs[1] >> 24) & 0x3F
    def set_chip(self, chip):
        self.regs[1] &= ~(0x3F << 24)
        self.regs[1] |= (chip & 0x3F) << 24;

    def ep(self):
        return self.regs[1] & 0xFFFF
    def set_ep(self, ep):
        self.regs[1] &= ~0xFFFF
        self.regs[1] |= ep & 0xFFFF

    def gen(self):
        return (self.regs[1] >> 30) & 0xFF

    def label(self):
        return self.regs[2]
    def set_label(self, label):
        self.regs[2] = label

    def msg_size(self):
        if self.version < 3:
            return (self.regs[0] >> 31) & 0x3F
        else:
            return (self.regs[0] >> 33) & 0x3F
    def set_msg_size(self, size):
        if self.version < 3:
            self.regs[0] &= ~(0x3F << 31)
            self.regs[0] |= (size & 0x3F) << 31
        else:
            self.regs[0] &= ~(0x3F << 33)
            self.regs[0] |= (size & 0x3F) << 33

    def max_crd(self):
        if self.version < 3:
            return (self.regs[0] >> 25) & 0x3F
        else:
            return (self.regs[0] >> 26) & 0x7F
    def cur_crd(self):
        if self.version < 3:
            return (self.regs[0] >> 19) & 0x3F
        else:
            return (self.regs[0] >> 19) & 0x7F
    def set_crd(self, crd):
        if self.version < 3:
            self.regs[0] &= ~((0x3F << 25) | (0x3F << 19))
            self.regs[0] |= (crd & 0x3F) << 25
            self.regs[0] |= (crd & 0x3F) << 19
        else:
            self.regs[0] &= ~((0x7F << 26) | (0x7F << 19))
            self.regs[0] |= (crd & 0x7F) << 26
            self.regs[0] |= (crd & 0x7F) << 19

    def is_reply(self):
        if self.version < 3:
            return (self.regs[0] >> 55) & 0x1
        else:
            return (self.regs[0] >> 53) & 0x1
    def crd_ep(self):
        if self.version < 3:
            return (self.regs[0] >> 37) & 0xFFFF
        else:
            return (self.regs[0] >> 39) & 0xFFFF

    def dynamic(self):
        return (self.regs[0] >> 62) & 0x1

    def frozen(self):
        return (self.regs[0] >> 63) & 0x1

    def __repr__(self):
        return "Send[dst={}-{}:ep{} gen{}, act={:#x}, label={:#x}, msgsz=2^{}, crd={}:{}, reply={}, dynamic={}, frozen={}]".format(
            self.chip(), modid_to_tile(self.tile()), self.ep(), self.gen(), self.act(), self.label(), self.msg_size(), self.cur_crd(),
            self.max_crd(), self.is_reply(), self.dynamic(), self.frozen()
        )

class RecvEP(EP):
    def __init__(self, version, regs = [EP.RECEIVE, 0, 0, 0]):
        super(RecvEP, self).__init__(version, regs)

    def buffer(self):
        return self.regs[1]
    def set_buffer(self, buffer):
        self.regs[1] = buffer

    def slot_size(self):
        if self.version < 3:
            return (self.regs[0] >> 41) & 0x3F
        else:
            return (self.regs[0] >> 42) & 0x3F
    def set_slot_size(self, size):
        if self.version < 3:
            self.regs[0] &= ~(0x3F << 42)
            self.regs[0] |= (size & 0x3F) << 42
        else:
            self.regs[0] &= ~(0x3F << 41)
            self.regs[0] |= (size & 0x3F) << 41

    def slots(self):
        if self.version < 3:
            return (self.regs[0] >> 35) & 0x3F
        else:
            return (self.regs[0] >> 35) & 0x7F
    def set_slots(self, slots):
        if self.version < 3:
            self.regs[0] &= ~(0x3F << 35)
            self.regs[0] |= (slots & 0x3F) << 35
        else:
            self.regs[0] &= ~(0x7F << 35)
            self.regs[0] |= (slots & 0x7F) << 35

    def reply_eps(self):
        return (self.regs[0] >> 19) & 0xFFFF
    def set_reply_eps(self, eps):
        self.regs[0] &= ~(0xFFFF << 19)
        self.regs[0] |= (eps & 0xFFFF) << 19

    def unread(self):
        if self.version < 3:
            return self.regs[2] >> 32
        else:
            return self.regs[3]
    def occupied(self):
        if self.version < 3:
            return self.regs[2] & 0xFFFFFFFF
        else:
            return self.regs[2]
    def rpos(self):
        if self.version < 3:
            return (self.regs[0] >> 53) & 0x3F
        else:
            return (self.regs[0] >> 55) & 0x7F
    def wpos(self):
        if self.version < 3:
            return (self.regs[0] >> 47) & 0x3F
        else:
            return (self.regs[0] >> 48) & 0x7F

    def dynamic(self):
        return (self.regs[0] >> 62) & 0x1

    def frozen(self):
        return (self.regs[0] >> 63) & 0x1

    def __repr__(self):
        return "Recv[buffer={:#x}, act={:#x}, slots=2^{}, slot_size=2^{}, unread={:#x}, occupied={:#x}, rpl_eps={}, rpos={}, wpos={}, dynamic={}, frozen={}]".format(
            self.buffer(), self.act(), self.slots(), self.slot_size(), self.unread(), self.occupied(),
            self.reply_eps(), self.rpos(), self.wpos()
        )

class TileDesc():
    TILE_TYPE = ["COMP", "MEM"]
    TILE_ISA = ["NONE", "RISCV64", "RISCV32"]
    TILE_ATTR = ["BOOM", "ROCKET", "NIC", "SERIAL", "IMEM", "IEPS", "PicoRV", "ACC-AES", "ACC-Hash"]
    def __init__(self, desc):
        self.tile_type = desc & 0x2F
        self.tile_isa = (desc >> 6) & 0x1F
        self.tile_attr = (desc >> 11) & 0x1FFFF
        self.tile_memsize = desc >> 28

    def type(self):
        return self.TILE_TYPE[self.tile_type]

    def isa(self):
        return self.TILE_ISA[self.tile_isa]

    def attrs(self):
        attr_str = ""
        for attr_bit in range(0, len(self.TILE_ATTR)):
            if (self.tile_attr >> attr_bit) & 0x1:
                attr_str += "" if not attr_str else " "
                attr_str += self.TILE_ATTR[attr_bit]

        #'NONE' if it is neither mem nor core
        if not attr_str:
            attr_str = "NONE"
        return attr_str

    def memsize(self):
        return (self.tile_memsize << 12)

    def __repr__(self):
        return "TileDesc: type={}, isa={}, attr={}, mem-size={:#x}".format(
            self.type(), self.isa(), self.attrs(), self.memsize())


class TCUExtRegV2(Enum):
    FEATURES = 0
    TILE_DESC = 1
    EXT_CMD = 2

class TCUExtRegV3(Enum):
    FEATURES = 0
    TILE_DESC = 1
    EXT_CMD = 2
    EXT_EPS_ADDR = 3
    EXT_EPS_SIZE = 4
    EXT_EXREG_MNG = 5

class TCUExtRegV4(Enum):
    FEATURES = 0
    TILE_DESC = 1
    EXT_CMD = 2
    EXT_ARG1 = 3
    EXT_EPS_ADDR = 4
    EXT_EPS_SIZE = 5
    EXT_EXREG_MNG = 6

class TCUStatusRegV3(Enum):
    STATUS = 0
    RESET = 1
    CLKFREQ = 2
    TIMEOUT_SEND = 3
    TIMEOUT_RECV = 4
    REGADDR_CU_REQ_INT = 5
    REGADDR_TIMER_INT = 6
    CTRL_FLIT_COUNT = 7
    BYP_FLIT_COUNT = 8
    DROP_FLIT_COUNT = 9

class TCUStatusRegV4(Enum):
    STATUS = 0
    RESET = 1
    CLKFREQ = 2
    TIMEOUT_SEND = 3
    TIMEOUT_RECV = 4
    REGADDR_CU_REQ_INT = 5
    REGADDR_TIMER_INT = 6
    PMP_OFFSET = 7
    STRM_COUNT_EXT_EP = 8
    STRM_COUNT_LOC_DMA = 9
    STRM_COUNT_EXT_DMA = 10
    STRM_COUNT_LOC_MSG = 11
    STRM_COUNT_EXT_MSG = 12
    STRM_COUNT_PMP = 13
    STRM_COUNT_BYPASS = 14


class TCUError():
    ERROR_CODES = [
        "NONE",
        "NO_MEP",
        "NO_SEP",
        "NO_REP",
        "FOREIGN_EP",
        "SEND_REPLY_EP",
        "RECV_GONE",
        "RECV_NO_SPACE",
        "REPLIES_DISABLED",
        "OUT_OF_BOUNDS",
        "NO_CREDITS",
        "NO_PERM",
        "INV_MSG_OFF",
        "TRANSLATION_FAULT",
        "ABORT",
        "UNKNOWN_CMD",
        "RECV_OUT_OF_BOUNDS",
        "RECV_INV_RPL_EPS",
        "SEND_INV_CRD_EP",
        "SEND_INV_MSG_SZ",
        "TIMEOUT_MEM",
        "TIMEOUT_NOC",
        "PAGE_BOUNDARY",
        "MSG_UNALIGNED",
        "TLB_MISS",
        "TLB_FULL",
        "NO_PMP_EP",
        "NO_IRQ",
        "EXREG_NO_PERM",
        "EXREG_NO_MNG",
        "TILE_LOCKED",
        "WRONG_GEN",
        "EP_FROZEN",
        "EP_NOT_FROZEN",
        "CRITICAL"]

    def print_error(error_code):
        if error_code < len(TCUError.ERROR_CODES):
            return TCUError.ERROR_CODES[error_code]
        else:
            return "Unknown error code({})".format(error_code)

class TCU():
    EP_COUNT = 128
    BASE_ADDR = 0xF000_0000
    LOG_OFF = 0x0100_0000

    def __init__(self, version):
        self.version = version
        if version < 3:
            self.TCUExtReg = TCUExtRegV2
            self.TCUStatusReg = TCUStatusRegV3
            self.status_off = 0x0000_3000
            self.config_off = 0x0000_3028
        elif version < 4:
            self.TCUExtReg = TCUExtRegV3
            self.TCUStatusReg = TCUStatusRegV3
            self.status_off = 0x0000_3000
            self.config_off = 0x0000_3028
        else:
            self.TCUExtReg = TCUExtRegV4
            self.TCUStatusReg = TCUStatusRegV4
            self.status_off = 0x0020_2000
            self.config_off = 0x0020_3000

    def ep_count(self):
        return TCU.EP_COUNT

    def ext_reg_addr(self, reg):
        assert isinstance(reg, self.TCUExtReg)
        return TCU.BASE_ADDR + reg.value * 8

    def eps_addr(self):
        if self.version == 1:
            return TCU.BASE_ADDR + 0x0000_0040
        if self.version == 2:
            return TCU.BASE_ADDR + 0x0000_0048
        return TCU.BASE_ADDR + 0x0000_2000

    def ep_addr(self, ep):
        if self.version < 3:
            return self.eps_addr() + ep * (8 * 3)
        else:
            return self.eps_addr() + ep * (8 * 4)

    def status_reg_addr(self, reg):
        assert isinstance(reg, self.TCUStatusReg)
        return TCU.BASE_ADDR + self.status_off + reg.value * 8

    def config_reg_addr(self, reg):
        return TCU.BASE_ADDR + self.config_off + reg.value * 8

    def log_addr(self):
        return TCU.BASE_ADDR + TCU.LOG_OFF
