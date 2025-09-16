
from enum import Enum

class RocketConfigReg(Enum):
    ENABLE = 0
    INT0 = 1
    TCU_AXI_BRIDGE_ERROR = 6
    MEM_AXI_BRIDGE_ERROR = 7
    TRACE_ENABLE = 8
    TRACE_IDX0 = 9
    TRACE_COUNT0 = 10
    TRACE_IDX1 = 11
    TRACE_COUNT1 = 12

class PM():
    #Rocket interrupt
    ROCKET_INT_COUNT = 2
    ROCKET_TRACEMEM_BASE = 0x00100000
    ROCKET_TRACEMEM_SIZE = 1024

    def __init__(self, tcu, mem, pmNum):
        self.tcu = tcu
        self.mem = mem
        self.name = "PM%d" % pmNum

    def __repr__(self):
        return self.name

    def start(self):
        self.mem[self.tcu.config_reg_addr(RocketConfigReg.ENABLE)] = 1

    def stop(self):
        self.mem[self.tcu.config_reg_addr(RocketConfigReg.ENABLE)] = 0

    def getEnable(self):
        return self.mem[self.tcu.config_reg_addr(RocketConfigReg.ENABLE)]

    #----------------------------------------------
    #special functions for Rocket RISC-V core

    #interrupt val
    def rocket_setInt(self, int_num, val):
        if (int_num < self.ROCKET_INT_COUNT):
            self.mem[self.tcu.config_reg_addr(RocketConfigReg.INT0) + int_num*8] = val
        else:
            print("Interrupt %d not supported for Rocket core. Max = %d" % (int_num, self.ROCKET_INT_COUNT))

    def rocket_getInt(self, int_num):
        if (int_num < self.ROCKET_INT_COUNT):
            return self.mem[self.tcu.config_reg_addr(RocketConfigReg.INT0) + int_num*8]
        else:
            print("Interrupt %d not supported for Rocket core. Max = %d" % (int_num, self.ROCKET_INT_COUNT))
            return 0

    #start core via interrupt 0
    def rocket_start(self):
        self.rocket_setInt(0, 1)

    def rocket_getTCUAXIBridgeError(self):
        return self.mem[self.tcu.config_reg_addr(RocketConfigReg.TCU_AXI_BRIDGE_ERROR)]

    def rocket_getAXIMemBridgeError(self):
        return self.mem[self.tcu.config_reg_addr(RocketConfigReg.MEM_AXI_BRIDGE_ERROR)]

    def rocket_enableTrace(self):
        self.mem[self.tcu.config_reg_addr(RocketConfigReg.TRACE_ENABLE)] = 1

    def rocket_disableTrace(self):
        self.mem[self.tcu.config_reg_addr(RocketConfigReg.TRACE_ENABLE)] = 0

    def rocket_printCombinedTrace(self, filename, trace):
        f = open(filename, "w")
        f.write(f"Rocket instruction trace of {self.name}:\n")
        trace.sort(key=lambda event: event[0])
        for ev in trace:
            time, addr, opcode, priv, exc, irq, cause, tval = ev
            f.write(f"{time:<10} {addr:#010x} {opcode:#010x} {priv:d} {exc:d} {irq:d} " +
                    f"{cause:#018x} {tval:#010x}\n")
        f.close()

    def rocket_getTrace(self, all=False, traceNum=0):
        #select trace memory
        if traceNum == 0:
            reg_trace_idx = RocketConfigReg.TRACE_IDX0
            reg_trace_count = RocketConfigReg.TRACE_COUNT0
            mem_offset = 0
        else:
            reg_trace_idx = RocketConfigReg.TRACE_IDX1
            reg_trace_count = RocketConfigReg.TRACE_COUNT1
            mem_offset = self.ROCKET_TRACEMEM_SIZE*32

        #make sure trace is stopped before reading it
        self.rocket_disableTrace()

        #read trace count
        trace_count = self.mem[self.tcu.config_reg_addr(reg_trace_count) + mem_offset]
        if all:
            trace_count = self.ROCKET_TRACEMEM_SIZE

        print(f"{self.name}: Number of Rocket instruction traces" +
              f"(mem {traceNum + 1}): {trace_count}")

        res = []
        if trace_count > 0:
            #read current idx to calculate address of first trace
            trace_current_idx = self.mem[self.tcu.config_reg_addr(reg_trace_idx) + mem_offset]
            if trace_current_idx >= trace_count:
                trace_start_idx = trace_current_idx - trace_count
            else:
                trace_start_idx = self.ROCKET_TRACEMEM_SIZE + trace_current_idx - trace_count
            trace_start_addr = self.ROCKET_TRACEMEM_BASE + 32*trace_start_idx

            tmp_count = trace_count
            #reduce tmp_count if traces wrap around
            if (trace_start_idx+trace_count) > self.ROCKET_TRACEMEM_SIZE:
                tmp_count = self.ROCKET_TRACEMEM_SIZE - trace_start_idx

            #read traces, one trace occupies 32 byte
            trace_data = self.mem.read_words(trace_start_addr+mem_offset, tmp_count*4)

            #read the rest from start of trace memory
            if tmp_count < trace_count:
                trace_data_rest = self.mem.read_words(self.ROCKET_TRACEMEM_BASE+mem_offset, (trace_count-tmp_count)*4)
                trace_data.extend(trace_data_rest)

            #extract info
            for i in range(0, trace_count*4, 4):
                trace_addr = trace_data[i] & 0xFFFFFFFF
                trace_opcode = trace_data[i] >> 32
                trace_priv = trace_data[i+1] & 0x7
                trace_except = (trace_data[i+1] >> 3) & 0x1
                trace_int = (trace_data[i+1] >> 4) & 0x1
                trace_cause = ((trace_data[i+2] & 0x1F) << 59) |  (trace_data[i+1] >> 5)
                trace_tval = (trace_data[i+2] >> 5) & 0xFFFFFFFFFF
                trace_time = ((trace_data[i+3] & 0x1FFF) << 19) |  (trace_data[i+2] >> 45)
                res.append((trace_time, trace_addr, trace_opcode, trace_priv, trace_except,
                            trace_int, trace_cause, trace_tval))

        return res
