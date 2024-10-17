
import memory

class DRAM(memory.Memory):
    def __init__(self, mem):
        self.mem = mem
        self.shortname = "dram"
        self.name = "DDR4 SDRAM"

    def __repr__(self):
        return self.name

    def getStatus(self):
        return self.mem[self.tcu.config_reg_addr(0)]

    def getInitCalibComplete(self):
        return self.mem[self.tcu.config_reg_addr(1)]

