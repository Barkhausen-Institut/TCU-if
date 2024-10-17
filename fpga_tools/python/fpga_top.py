
import modids
import noc
import router
import ethernet
import dram
import tile
import uart
import regfile
from tcu import TCU

import sys
from ipaddress import IPv4Address


class fpga:
    def getmod(self, ident):
        if isinstance(ident, int):
            for mod in self.mods:
                try:
                    if mod.thadr[1] == ident:
                        return mod
                except AttributeError:
                    pass
        if isinstance(ident, str):
            for mod in self.mods:
                try:
                    if mod.shortname == ident:
                        return mod
                except AttributeError:
                    pass
        return None


class FPGA_TOP(fpga):
    #dedicated addr range for FPGA: 192.168.42.240-254
    FPGA_IP = '192.168.42.240'
    FPGA_PORT = 1800
    def __init__(self, version, fpga_sw=0, reset=0, use_uart=False):
        if fpga_sw >= 15:
            print("Invalid FPGA IP address selected! Only use 192.168.42.240-254")
            raise ValueError

        self.fpga_ip_addr = str(IPv4Address(int(IPv4Address(self.FPGA_IP)) + fpga_sw))

        print("Connect to FPGA (fpga_ip={}, fpga_port={})".format(self.fpga_ip_addr, self.FPGA_PORT))
        if reset: print("FPGA Reset...")
        sys.stdout.flush()

        #DIP switch determines Chip-ID
        chipid = fpga_sw

        #periphery
        if use_uart:
            self.uart = uart.UART('/dev/ttyUSB1')

        tcu = TCU(version)

        #NOC
        self.nocif = noc.NoCethernet(tcu, (self.fpga_ip_addr, self.FPGA_PORT), chipid, reset)

        #Ethernet tile
        self.eth_rf = tile.Tile(tcu, self.nocif, (chipid, modids.MODID_ETH))

        #regfile
        #self.regfile = regfile.REGFILE(self.nocif, (chipid, modids.MODID_PM5))

        #NoC router
        self.router_count = router.Router.ROUTER_CNT
        self.router = [router.Router(self.nocif, (chipid, modids.MODID_ROUTER[x]), x) for x in range(self.router_count)]

        #DRAM
        self.dram1 = tile.Tile(tcu, self.nocif, (chipid, modids.MODID_DRAM1))
        self.dram2 = tile.Tile(tcu, self.nocif, (chipid, modids.MODID_DRAM2))

        #PMs
        self.pm_count = len(modids.MODID_PMS)
        self.pmTiles = [tile.Tile(tcu, self.nocif, (chipid, modids.MODID_PMS[x]), x) for x in range(self.pm_count)]

    def set_arq_enable(self, enabled):
        val = 1 if enabled else 0
        for pm in self.pmTiles:
            pm.nocarq.set_arq_enable(val)
            if enabled:
                pm.nocarq.set_arq_timeout(200)  # reduce timeout
        self.eth_rf.nocarq.set_arq_enable(val)
        self.dram1.nocarq.set_arq_enable(val)
        self.dram2.nocarq.set_arq_enable(val)

    def tear(self):
        self.noccomm.tear()
        self.uart.close()
