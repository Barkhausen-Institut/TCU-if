import string
from enum import Enum

class AccConfigReg(Enum):
    ASM_EN = 0
    ACC_EN = 1
    PICO_TRAP = 2
    PICO_IRQ = 3
    PICO_EOI = 4
    PICO_STACKADDR = 5

class AESConfigReg(Enum):
    STATE_ADDR = 6
    KEY_ADDR = 7
    OUT_ADDR = 8

#todo: keccak config addresses

class ACC():
    PICO_INT_COUNT = 32

    def __init__(self, tcu, mem, pm_num, name:string):
        self.tcu = tcu
        self.name = "PM%d (%s)" % (pm_num, name)
        self.mem = mem

    def __repr__(self):
        return self.name

    def asm_enable(self):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_EN)] = 1

    def asm_disable(self):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_EN)] = 0

    def asm_getEnable(self):
        return self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_EN)]

    def acc_enable(self):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.ACC_EN)] = 1

    def acc_disable(self):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.ACC_EN)]= 0

    def acc_getEnable(self):
        return self.mem[self.tcu.config_reg_addr(AccConfigReg.ACC_EN)]

    def pico_getInt(self, int_num):
        if (int_num < ACC.PICO_INT_COUNT):
            return (self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_IRQ)] >> int_num) & 0x1
        else:
            print("Interrupt %d not supported for PicoRV32 core. Max = %d" % (int_num, ACC.PICO_INT_COUNT))
            return 0

    def pico_setInt(self, int_num, val:bool):
        if (int_num < ACC.PICO_INT_COUNT):
            tmp_irq = self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_IRQ)]
            self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_IRQ)] = tmp_irq | (int(val) << int_num)
        else:
            print("Interrupt %d not supported for PicoRV32 core. Max = %d" % (int_num, ACC.PICO_INT_COUNT))

    #When the interrupt handler is started, the End Of Interrupt (EOI) signals for the handled interrupts go high.
    #The EOI signals go low again when the interrupt handler returns.
    def pico_getEOI(self, eoi_num):
        if (eoi_num < ACC.PICO_INT_COUNT):
            return (self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_EOI)] >> eoi_num) & 0x1
        else:
            print("Interrupt %d not supported for PicoRV32 core. Max = %d" % (eoi_num, ACC.PICO_INT_COUNT))
            return 0

    def pico_getTrap(self):
        return self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_TRAP)]

    #default stack addr is the end of ASM's DMEM: 0x10000
    def pico_setStackaddr(self, addr):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_STACKADDR)] = addr

    def pico_getStackaddr(self):
        return self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_STACKADDR)]


    #----------------------------------------------
    #special functions for AES core
    def aes_setAddrs(self, state, key, out):
        self.mem[self.tcu.config_reg_addr(AESConfigReg.STATE_ADDR)] = state
        self.mem[self.tcu.config_reg_addr(AESConfigReg.KEY_ADDR)] = key
        self.mem[self.tcu.config_reg_addr(AESConfigReg.OUT_ADDR)] = out

