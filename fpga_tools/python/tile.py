from enum import Enum

import noc
import memory
import pm
import acc
import dram
import ethernet
from tcu import TCUStatusReg, TCUExtReg, EP, LOG, TileDesc

class TileType(Enum):
    ROCKET = 0
    ACC = 1
    ETH = 2
    DRAM = 3

class Tile():
    def __init__(self, tcu, nocif, nocid, pmNum=0, showDesc=False):
        self.tcu = tcu
        self.nocif = nocif
        self.nocid = nocid
        self.id = "C{:x}-M{:02x}".format(nocid[0], nocid[1])
        self.name = None
        self.mem = memory.Memory(nocif, self.nocid)
        self.nocarq = noc.NoCARQRegfile(self.nocid)
        self.pmNum = pmNum  #only used for PMs
        self.type = None
        self.desc = self.tcu_tile_desc()
        self.inst = self.setTileInst(self.desc)
        if showDesc:
            print("{}: {}".format(self.name, self.desc))

    def __repr__(self):
        return self.name

    def setTileInst(self, desc):
        #check tile content and assign tile instance
        tileInst = None
        if desc.type() == "COMP":
            if desc.isa() == "RISC-V":
                if "ROCKET" in desc.attrs() or "BOOM" in desc.attrs():
                    #found Rocket or BOOM core
                    tileInst = pm.PM(self.tcu, self.mem, self.pmNum)
                    self.type = TileType.ROCKET
                    self.name = "PM{}".format(self.pmNum)
                elif "IMEM" in desc.attrs():
                    #todo: this should be obtained from tile description, too
                    if self.pmNum == 3:
                        accName = "AES"
                    elif self.pmNum == 4:
                        accName = "Hash"
                    else:
                        accName = "Unknown accelerator"
                    #found accelerator
                    tileInst = acc.ACC(self.tcu, self.mem, self.pmNum, accName)
                    self.type = TileType.ACC
                    self.name = "PM{}".format(self.pmNum)
        
        #desc.type == MEM
        else:
            if "IMEM" in desc.attrs() and desc.memsize() > 0:
                tileInst = dram.DRAM(self.mem)
                self.type = TileType.DRAM
                self.name = "DRAM"
            elif "NONE" in desc.attrs() and desc.memsize() == 0:
                tileInst = ethernet.EthernetRegfile(self.tcu, self.mem, self.nocif)
                self.type = TileType.ETH
                self.name = "ETH"

        if tileInst == None or self.type == None:
            print("Warning: Could not identify tile instance and type for tile {}".format(self.id))
        return tileInst


    def tcu_get_ep(self, ep_id):
        r0 = self.mem[self.tcu.ep_addr(ep_id) + 0]
        r1 = self.mem[self.tcu.ep_addr(ep_id) + 8]
        r2 = self.mem[self.tcu.ep_addr(ep_id) + 16]
        return EP.from_regs([r0, r1, r2])

    def tcu_set_ep(self, ep_id, ep):
        self.mem[self.tcu.ep_addr(ep_id) + 0] = ep.regs[0]
        self.mem[self.tcu.ep_addr(ep_id) + 8] = ep.regs[1]
        self.mem[self.tcu.ep_addr(ep_id) + 16] = ep.regs[2]

    def tcu_set_features(self, priv, vm, ctxsw):
        flags = ((ctxsw & 0x1) << 2) | ((vm & 0x1) << 1) | (priv & 0x1)
        #TCU version cannot be changed
        self.mem[self.tcu.ext_reg_addr(TCUExtReg.FEATURES)] = flags

    def tcu_version(self):
        version = self.mem[self.tcu.ext_reg_addr(TCUExtReg.FEATURES)] >> 32
        vmajor = version & 0xFFFF
        vminor = (version >> 16) & 0xFF
        vpatch = (version >> 24) & 0xFF
        return (vmajor, vminor, vpatch)

    def tcu_tile_desc(self):
        tile_desc = self.mem[self.tcu.ext_reg_addr(TCUExtReg.TILE_DESC)]
        return TileDesc(tile_desc)

    def tcu_status(self):
        status = self.mem[self.tcu.status_reg_addr(TCUStatusReg.STATUS)]
        return (status & 0xFF, (status >> 8) & 0xFF, (status >> 16) & 0xFF, (status >> 24) & 0xFF)

    def tcu_reset(self):
        self.mem[self.tcu.status_reg_addr(TCUStatusReg.RESET)] = 1

    def tcu_ctrl_flit_count(self):
        flits = self.mem[self.tcu.status_reg_addr(TCUStatusReg.CTRL_FLIT_COUNT)]
        flits_rx = flits & 0xFFFFFFFF
        flits_tx = flits >> 32
        return (flits_tx, flits_rx)

    def tcu_byp_flit_count(self):
        flits = self.mem[self.tcu.status_reg_addr(TCUStatusReg.BYP_FLIT_COUNT)]
        flits_rx = flits & 0xFFFFFFFF
        flits_tx = flits >> 32
        return (flits_tx, flits_rx)

    def tcu_drop_flit_count(self):
        return self.mem[self.tcu.status_reg_addr(TCUStatusReg.DROP_FLIT_COUNT)] & 0xFFFFFFFF

    def tcu_error_flit_count(self):
        return self.mem[self.tcu.status_reg_addr(TCUStatusReg.DROP_FLIT_COUNT)] >> 32

    def tcu_print_log(self, filename, all=False):
        # open and truncate file first (reads below might fail)
        fh = open(filename, 'w')

        if all:
            log_count = 65536
        else:
            log_count = self.mem[self.tcu.log_addr()]

        print("%s: Number of TCU log messages: %d" % (self.name, log_count))
        if log_count > 65536:
            fh.write("%s: Number of TCU log messages: %d (only 65536 shown, last log at %d)\n" % (self.name, log_count, log_count%65536-1))
            log_count = 65536
        else:
            fh.write("%s: Number of TCU log messages: %d\n" % (self.name, log_count))

        #read log mem: first log is at TCU_REGADDR_TCU_LOG+0x10
        if log_count > 0:
            for i in range(log_count):
                lower = self.mem[self.tcu.log_addr() + 0x10 + i * 16]
                upper = self.mem[self.tcu.log_addr() + 0x18 + i * 16]
                fh.write("%5d: %s\n" % (i, LOG.split_tcu_log(self.tcu.version, upper, lower)))
        fh.close()

    def tcu_set_log_mask(self, mask):
        """
        Set log selection mask. Default value: 0xFFFFFFFF
        Each bit of the mask represents a log id from list TCU.LOG_ID starting with bit 0 = CMD_SEND
        If the bit in the mask is set, the TCU writes the log with this id to log mem.
        """
        self.mem[self.tcu.log_addr() + 8] = mask

    def tcu_get_log_mask(self):
        return self.mem[self.tcu.log_addr() + 8]
