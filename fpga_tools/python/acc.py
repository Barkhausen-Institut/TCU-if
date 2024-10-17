import string
from enum import Enum

class AccConfigReg(Enum):
    ASM_EN = 0
    ACC_EN = 1
    PICO_TRAP = 2
    PICO_IRQ = 3
    PICO_EOI = 4
    PICO_STACKADDR = 5

    ASM_TRACE_ENABLE = 10
    ASM_TRACE_PTR = 11
    ASM_TRACE_COUNT = 12

class AESConfigReg(Enum):
    STATE_ADDR = 6
    KEY_ADDR = 7
    OUT_ADDR = 8

#todo: keccak config addresses

class ACC():
    #ASM IMEM: start addr at 0x0, 64kB
    #ASM DMEM: start addr at 0x10000, 16kB
    ASM_IMEM_START_ADDR = 0x0
    ASM_IMEM_SIZE = 0x10000
    ASM_DMEM_START_ADDR = ASM_IMEM_START_ADDR + ASM_IMEM_SIZE
    ASM_DMEM_SIZE = 0x4000

    #ACC MEM: start addr at 0x14000, 4kB
    ACC_MEM_START_ADDR = ASM_DMEM_START_ADDR + ASM_DMEM_SIZE
    ACC_MEM_SIZE = 0x1000

    PICO_INT_COUNT = 32

    ASM_TRACEMEM_BASE = 0x00100000
    ASM_TRACEMEM_SIZE = 1024


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

    def asm_getInt(self, int_num):
        if (int_num < ACC.PICO_INT_COUNT):
            return (self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_IRQ)] >> int_num) & 0x1
        else:
            print("Interrupt %d not supported for PicoRV32 core. Max = %d" % (int_num, ACC.PICO_INT_COUNT))
            return 0

    def asm_setInt(self, int_num, val:bool):
        if (int_num < ACC.PICO_INT_COUNT):
            tmp_irq = self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_IRQ)]
            self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_IRQ)] = tmp_irq | (int(val) << int_num)
        else:
            print("Interrupt %d not supported for PicoRV32 core. Max = %d" % (int_num, ACC.PICO_INT_COUNT))

    #When the interrupt handler is started, the End Of Interrupt (EOI) signals for the handled interrupts go high.
    #The EOI signals go low again when the interrupt handler returns.
    def asm_getEOI(self, eoi_num):
        if (eoi_num < ACC.PICO_INT_COUNT):
            return (self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_EOI)] >> eoi_num) & 0x1
        else:
            print("Interrupt %d not supported for PicoRV32 core. Max = %d" % (eoi_num, ACC.PICO_INT_COUNT))
            return 0

    def asm_getTrap(self):
        return self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_TRAP)]

    #default stack addr is the end of ASM's DMEM: 0x10000
    def asm_setStackaddr(self, addr):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_STACKADDR)] = addr

    def asm_getStackaddr(self):
        return self.mem[self.tcu.config_reg_addr(AccConfigReg.PICO_STACKADDR)]

    def asm_enableTrace(self):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_TRACE_ENABLE)] = 1

    def asm_disableTrace(self):
        self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_TRACE_ENABLE)] = 0

    def asm_printTrace(self, filename, all=False):
        #make sure trace is stopped before reading it
        self.asm_disableTrace()

        #open file first (reads below might fail)
        fh = open(filename, 'w')

        #read trace count
        trace_count = self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_TRACE_COUNT)]
        if all:
            trace_count = self.ASM_TRACEMEM_SIZE

        print("%s: Number of PicoRV32 instruction traces: %d" % (self.name, trace_count))
        fh.write("%s: Number of PicoRV32 instruction traces: %d\n" % (self.name, trace_count))

        if trace_count > 0:
            #read current idx to calculate address of first trace
            trace_current_idx = self.mem[self.tcu.config_reg_addr(AccConfigReg.ASM_TRACE_PTR)]
            if trace_current_idx >= trace_count:
                trace_start_idx = trace_current_idx - trace_count
            else:
                trace_start_idx = self.ASM_TRACEMEM_SIZE + trace_current_idx - trace_count
            trace_start_addr = self.ASM_TRACEMEM_BASE + 8*trace_start_idx

            tmp_count = trace_count
            #reduce tmp_count if traces wrap around
            if (trace_start_idx+trace_count) > self.ASM_TRACEMEM_SIZE:
                tmp_count = self.ASM_TRACEMEM_SIZE - trace_start_idx

            #read traces, one trace occupies 8 byte
            trace_data = self.mem.read_words(trace_start_addr, tmp_count)

            #read the rest from start of trace memory
            if tmp_count < trace_count:
                trace_data_rest = self.mem.read_words(self.ASM_TRACEMEM_BASE, trace_count-tmp_count)
                trace_data.extend(trace_data_rest)

            #print to file
            for i in range(trace_count):
                fh.write("{:#011x}\n".format(trace_data[i]))

        fh.close()


    #----------------------------------------------
    #special functions for AES core
    def aes_setAddrs(self, state, key, out):
        self.mem[self.tcu.config_reg_addr(AESConfigReg.STATE_ADDR)] = state
        self.mem[self.tcu.config_reg_addr(AESConfigReg.KEY_ADDR)] = key
        self.mem[self.tcu.config_reg_addr(AESConfigReg.OUT_ADDR)] = out

