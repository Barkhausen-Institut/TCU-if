"""
this module implements the driver for the NoC access via ethernet based on a Rust backend
"""
import threading
import time
import re

from fpga_utils import FPGA_Error

import nocrw

class NoCethernet(object):
    def __init__(self, tcu, send_ipaddr, chip_id, reset):
        self.tcu = tcu
        nocrw.connect(send_ipaddr[0], send_ipaddr[1], chip_id, reset)

    def read_bytes(self, trg_id, addr, len):
        return nocrw.read_bytes(trg_id[0], trg_id[1], addr, len)

    def write_bytes(self, trg_id, addr, bytes, burst=False):
        write_bytes_ret = nocrw.write_bytes(trg_id[0], trg_id[1], addr, bytes, burst)
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
