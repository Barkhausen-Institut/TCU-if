"""
this module implements the driver for the NoC access via ethernet based on a Rust backend
"""
import threading
import time
import re

from fpga_utils import FPGA_Error

import nocrw

class NoCethernet(object):
    def __init__(self, tcu, send_ipaddr, chip_id, tcu_major, reset):
        self.tcu = tcu
        self.tcu_major = tcu_major
        nocrw.connect(send_ipaddr[0], send_ipaddr[1], chip_id, tcu_major, reset)

    def read_bytes(self, trg_id, addr, len):
        return nocrw.read_bytes(trg_id[0], trg_id[1], addr, len)

    def write_bytes(self, trg_id, addr, bytes, burst=False):
        write_bytes_ret = nocrw.write_bytes(trg_id[0], trg_id[1], addr, bytes, burst)
        if self.tcu_major == 4:
            self.receive_bytes()
        return write_bytes_ret

    def send_bytes(self, trg_id, trg_ep, bytes):
        return nocrw.send_bytes(self.tcu.version, trg_id[0], trg_id[1], trg_ep, bytes)

    def receive_bytes(self, timeout_ns=1000_000_000):
        return nocrw.receive_bytes(timeout_ns)

class NoCmonitor(threading.Thread):
    regex_udp = r'\s+\d+:\s(\w+):(\w+)(\s+[\w:]+){10}\s(\d+)'
    check_udp_delay = 2.0

    def __init__(self):
        self.dropmap = {}
        super(NoCmonitor, self).__init__()
        self.daemon = True
        self.start()

    def run(self):
        while True:
            self.checkdrops()
            time.sleep(self.check_udp_delay)

    def checkdrops(self):
        fh = open("/proc/net/udp", "r")
        for l in fh:
            m = re.match(self.regex_udp, l)
            if not m:
                continue
            #TODO only check our connection
            madr = "%s:%s" % (m.group(1), m.group(2))
            drops = int(m.group(4))
            if madr not in self.dropmap:
                self.dropmap[madr] = 0
            if drops > self.dropmap[madr]:
                print("WARN: detected a UDP packet drop in /proc/net/udp:%s:%d" % (madr, drops))
                #print l
                self.dropmap[madr] = drops
        fh.close()


class NoCARQRegfile(object):
    REGADDR_ARQ_ENABLE            = 0x00
    REGADDR_ARQ_TIMEOUT_RX_CYCLES = 0x08
    REGADDR_NOC_RX_COUNT          = 0x10
    REGADDR_NOC_RX_DROP           = 0x18
    REGADDR_NOC_TX_BVT_MOD_WR_PTR = 0x20
    REGADDR_NOC_TX_BVT_ACK_WR_PTR = 0x28
    REGADDR_NOC_TX_BVT_OCC_PTR    = 0x30
    REGADDR_NOC_TX_BVT_RD_PTR     = 0x38
    REGADDR_NOC_RX_STATUS         = 0x40

    def __init__(self, nocid):
        self.nocid = nocid

    def read8b_nocarq(self, trg_id, addr):
        data = nocrw.read8b_nocarq(trg_id[0], trg_id[1], addr)
        return int.from_bytes(data[0:8], byteorder='little')

    def write8b_nocarq(self, trg_id, addr, word):
        assert isinstance(word, int), "word must be an integer"
        data = bytearray()
        data = word.to_bytes(8, byteorder='little')
        nocrw.write8b_nocarq(trg_id[0], trg_id[1], addr, bytes(data))

    def set_arq_enable(self, val):
        """
        Set enable for ARQ protocol. Possible input values:
        0: ARQ off, ARQ bit in NoC packet is forced to 0
        1: ARQ on, ARQ bit in NoC packet is forced to 1 (default)
        2: ARQ follows ARQ bit in packet
        """
        self.write8b_nocarq(self.nocid, self.REGADDR_ARQ_ENABLE, val)

    def get_arq_enable(self):
        return self.read8b_nocarq(self.nocid, self.REGADDR_ARQ_ENABLE)

    def set_arq_timeout(self, cycles):
        """
        Set timeout to drop packets when deadlock occurs. Default: 10000 cycles
        """
        self.write8b_nocarq(self.nocid, self.REGADDR_ARQ_TIMEOUT_RX_CYCLES, cycles)

    def get_arq_packet_count(self):
        """
        Number of received packets in NoC ARQ interface
        """
        return self.read8b_nocarq(self.nocid, self.REGADDR_NOC_RX_COUNT)

    def get_arq_drop_packet_count(self):
        """
        Number of received packets in NoC ARQ interface which were dropped
        """
        return self.read8b_nocarq(self.nocid, self.REGADDR_NOC_RX_DROP)

    def get_arq_tx_status(self):
        """
        Status info of TX part
        """
        bvt_mod_wr_ptr = self.read8b_nocarq(self.nocid, self.REGADDR_NOC_TX_BVT_MOD_WR_PTR)
        bvt_ack_wr_ptr = self.read8b_nocarq(self.nocid, self.REGADDR_NOC_TX_BVT_ACK_WR_PTR)
        bvt_occ_ptr = self.read8b_nocarq(self.nocid, self.REGADDR_NOC_TX_BVT_OCC_PTR)
        bvt_rd_ptr = self.read8b_nocarq(self.nocid, self.REGADDR_NOC_TX_BVT_RD_PTR)
        return (bvt_rd_ptr, bvt_occ_ptr, bvt_ack_wr_ptr, bvt_mod_wr_ptr)

    def get_arq_rx_status(self):
        """
        Status info of RX part
        """
        rx_status = self.read8b_nocarq(self.nocid, self.REGADDR_NOC_RX_STATUS)
        rxf_state = rx_status & 0x7
        rxf_full = (rx_status >> 3) & 0x1
        rxf_empty = (rx_status >> 4) & 0x1
        return (rxf_empty, rxf_full, rxf_state)
