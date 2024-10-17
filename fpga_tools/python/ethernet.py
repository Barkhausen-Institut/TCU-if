
from ipaddress import IPv4Address
from time import sleep

import memory
import modids


class EthernetRegfile(memory.Memory):
    def __init__(self, tcu, mem, nocif):
        self.tcu = tcu
        self.nocif = nocif
        self.shortname = "eth_rf"
        self.name = "Ethernet Regfile"
        self.rf = mem

    def __repr__(self):
        return self.name

    def self_test(self):
        hostif = memory.Memory(self.nocif, (0x3F, modids.MODID_ETH))
        test_addr = 0xDEAD_BEE0
        test_data = 0xFFDEBC9A_78563412
        hostif.write_word(test_addr, test_data)

    def system_reset(self):
        self.rf[self.tcu.config_reg_addr(0)] = 1
        print("FPGA System Reset...")
        sleep(5)   #need some time to get FPGA restarted

        #do self test to automatically set host IP address
        self.self_test()

        #check if link is up
        link_check = 3
        while link_check > 0:
            try:
                eth_status = self.getStatusVector()
            except:
                eth_status = 0
            intpyh_linkupandsync = eth_status & 0x3
            extphy_linkup = eth_status & 0x80 #for SGMII only
            if intpyh_linkupandsync == 0 or extphy_linkup == 0:
                #check again
                print("Ethernet link not set up. Check again.")
                link_check -= 1
                sleep(1)
            else:
                link_check = -1

        if link_check != -1:
            print("Could not reset FPGA!")

    def getStatusVector(self):
        return self.rf[self.tcu.config_reg_addr(1)]

    def getUDPstatus(self):
        return self.rf[self.tcu.config_reg_addr(2)]

    def getRXUDPerror(self):
        return self.rf[self.tcu.config_reg_addr(3)]

    def getMACstatus(self):
        return self.rf[self.tcu.config_reg_addr(4)]

    #FPGA IP address is set via DIP switch
    def getFPGAIP(self):
        return IPv4Address(self.rf[self.tcu.config_reg_addr(5)] & 0xFFFFFFFF)

    def setFPGAPort(self, fpga_port):
        self.rf[self.tcu.config_reg_addr(6)] = fpga_port

    def getFPGAPort(self):
        return self.rf[self.tcu.config_reg_addr(6)]

    #FPGA MAC address is set via DIP switch
    def getFPGAMAC(self):
        return self.rf[self.tcu.config_reg_addr(7)]

    def setHostIP(self, host_ip):
        self.rf[self.tcu.config_reg_addr(8)] = int(IPv4Address(host_ip))

    def getHostIP(self):
        return IPv4Address(self.rf[self.tcu.config_reg_addr(8)] & 0xFFFFFFFF)

    def setHostPort(self, host_port):
        self.rf[self.tcu.config_reg_addr(9)] = host_port

    def getHostPort(self):
        return self.rf[self.tcu.config_reg_addr(9)]
