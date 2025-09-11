
from tcu import modid_to_tile, TCUError, Flags

class LOG():
    LOG_ID_V3 = [
        "NONE",

        "CMD_SEND",
        "CMD_REPLY",
        "CMD_READ",
        "CMD_WRITE",
        "CMD_FETCH",
        "CMD_ACK_MSG",
        "CMD_FINISH",
        "RECV_FINISH",

        "CMD_EXT_INVEP",
        "CMD_EXT_FINISH",

        "NOC_REG_WRITE_ERR",
        "NOC_REG_WRITE",
        "NOC_READ_RSP",
        "NOC_READ_RSP_ERR",
        "NOC_READ_RSP_DONE",
        "NOC_WRITE",
        "NOC_READ_ERR",
        "NOC_READ",
        "NOC_MSG",
        "NOC_MSG_INV",
        "NOC_WRITE_ACK",
        "NOC_MSG_ACK",
        "NOC_ACK_ERR",
        "NOC_ERROR",
        "NOC_ERROR_UNEXP",
        "NOC_INVMODE",
        "NOC_INVFLIT",

        "CMD_PRIV_INV_PAGE",
        "CMD_PRIV_INV_TLB",
        "CMD_PRIV_INS_TLB",
        "CMD_PRIV_XCHG_VPE",
        "CMD_PRIV_SET_TIMER",
        "CMD_PRIV_ABORT",
        "CMD_PRIV_FINISH",
        "PRIV_CORE_REQ_FORMSG",
        "PRIV_CORE_REQ_PMPFAIL",
        "PRIV_CORE_REQ_FINISH",
        "PRIV_TLB_WRITE_ENTRY",
        "PRIV_TLB_READ_ENTRY",
        "PRIV_TLB_DEL_ENTRY",
        "PRIV_CUR_VPE_CHANGE",
        "PRIV_TIMER_INTR",
        "PMP_ACCESS_DENIED"
    ]

    LOG_ID_V4 = [
        "NONE",

        "CMD_SEND",
        "CMD_REPLY",
        "CMD_READ",
        "CMD_WRITE",
        "CMD_FETCH",
        "CMD_ACK_MSG",
        "CMD_UNFREEZE",
        "CMD_MKDYN",
        "CMD_FINISH",
        "RECV_FINISH",    #10

        "CMD_EXT_INVEP",
        "CMD_EXT_RESET",
        "CMD_EXT_FINISH",

        "NOC_READ_RSP",
        "NOC_READ_RSP_ERR",
        "NOC_READ_RSP_DONE",
        "NOC_READ",
        "NOC_MSG",
        "NOC_MSG_INV",
        "NOC_MSG_ACK",    #20
        "NOC_WRITE",
        "NOC_WRITE_ACK",
        "NOC_ACK_ERR",
        "NOC_PMP_WRITE",
        "NOC_PMP_READ",

        "CMD_PRIV_INV_PAGE",
        "CMD_PRIV_INV_TLB",
        "CMD_PRIV_INS_TLB",
        "CMD_PRIV_XCHG_ACT",
        "CMD_PRIV_SET_TIMER",    #30
        "CMD_PRIV_ABORT",
        "CMD_PRIV_FINISH",
        "PRIV_CU_REQ_FORMSG",
        "PRIV_CU_REQ_PMPFAIL",
        "PRIV_CU_REQ_FINISH",
        "PRIV_TLB_WRITE_ENTRY",
        "PRIV_TLB_READ_ENTRY",
        "PRIV_TLB_DEL_ENTRY",
        "PRIV_CUR_ACT_CHANGE",
        "PMP_ACCESS_DENIED",     #40
        "EXCLREG_ACCESS_DENIED",
        "DBG_PRINT"
    ]

    def split_tcu_log(version, clkfreq, upper_data64, lower_data64):
        log_id = (lower_data64 >> 32) & 0xFF
        log_time = int(((lower_data64 & 0xFFFFFFFF) * 1000) / clkfreq)
        id_string = LOG.get_tcu_log(version, log_id)
        time_string = "Time: {:12}".format(log_time)
        ret_string = time_string + ", " + id_string + ", "

        if (id_string == "NONE"):
            return ret_string

        #unpriv cmd
        if (id_string == "CMD_SEND"):
            log_ep = (lower_data64 >> 40) & 0xFFFF
            log_addr = ((upper_data64 & 0xFFFFFF) << 8) | (lower_data64 >> 56)
            log_size = (upper_data64 >> 24) & 0xFFFFFFFF
            log_modid = upper_data64 >> 56
            return ret_string + "to tile: {}, ep: {:d}, local addr: {:#010x}, size: {:d}".format(modid_to_tile(log_modid), log_ep, log_addr, log_size)

        if (id_string == "CMD_REPLY"):
            log_ep = (lower_data64 >> 40) & 0xFF
            log_addr = ((upper_data64 & 0xFFFF) << 16) | (lower_data64 >> 48)
            log_offset = (upper_data64 >> 16) & 0xFFFFF
            log_size = (upper_data64 >> 36) & 0xFFFFF
            log_modid = upper_data64 >> 56
            return ret_string + "to tile: {}, ep: {:d}, local addr: {:#010x}, msg offset: {:#x}, size: {:d}".format(modid_to_tile(log_modid), log_ep, log_addr, log_offset, log_size)

        if (id_string == "CMD_READ" or id_string == "CMD_WRITE"):
            log_ep = (lower_data64 >> 40) & 0xFF
            log_addr = ((upper_data64 & 0xFFFF) << 16) | (lower_data64 >> 48)
            log_offset = (upper_data64 >> 16) & 0xFFFFF
            log_size = (upper_data64 >> 36) & 0xFFFFF
            log_modid = upper_data64 >> 56
            return ret_string + "to tile: {}, ep: {:d}, local addr: {:#010x}, rem. addr offset: {:#x}, size: {:d}".format(modid_to_tile(log_modid), log_ep, log_addr, log_offset, log_size)

        if (id_string == "CMD_FETCH" or id_string == "CMD_ACK_MSG"):
            log_ep = (lower_data64 >> 40) & 0xFFFF
            log_slot_idx = lower_data64 >> 56
            return ret_string + "ep: {:d}, msg slot idx: {:d}".format(log_ep, log_slot_idx)

        if (id_string == "CMD_UNFREEZE" or id_string == "CMD_MKDYN"):
            log_ep = (lower_data64 >> 40) & 0xFFFF
            return ret_string + "ep: {:d}".format(log_ep)

        #unpriv finish
        if (id_string == "CMD_FINISH"):
            log_error = (lower_data64 >> 40) & 0x3F
            return ret_string + "error: {}".format(TCUError.print_error(log_error))

        #msg receive has been finished
        if (id_string == "RECV_FINISH"):
            if version < 4:
                log_occ_mask = ((upper_data64 & 0xFF) << 24) | (lower_data64 >> 40)
                log_unread_mask = (upper_data64 >> 8) & 0xFFFFFFFF
                log_bitpos = (upper_data64 >> 40) & 0xFFFF
                return ret_string + "orig. occ. mask: {:#010x}, orig. unread mask: {:#010x}, new set bit pos. in masks: {:#010x}".format(log_occ_mask, log_unread_mask, log_bitpos)
            else:
                log_error = (lower_data64 >> 40) & 0x3F
                log_ep = (lower_data64 >> 46) & 0xFFFF
                log_slot_idx = ((upper_data64 & 0x1F) << 2) | (lower_data64 >> 62)
                log_modid = upper_data64 >> 5
                return ret_string + "from tile: {}, ep: {}, msg slot idx: {:d}, error: {}".format(modid_to_tile(log_modid), log_ep, log_slot_idx, TCUError.print_error(log_error))

        #ext cmd
        if (id_string == "CMD_EXT_INVEP"):
            log_ep = (lower_data64 >> 40) & 0xFFFF
            log_force = (lower_data64 >> 56) & 0x1
            return ret_string + "ep: {:d}, force: {:d}".format(log_ep, log_force)

        if (id_string == "CMD_EXT_RESET"):
            log_start_core = (lower_data64 >> 40) & 0x1
            return ret_string + "{} core".format("start" if log_start_core else "stop")

        #ext finish
        if (id_string == "CMD_EXT_FINISH"):
            log_error = (lower_data64 >> 40) & 0x3F
            return ret_string + "error: {}".format(TCUError.print_error(log_error))

        #NoC received write or read
        if version < 4:
            if (id_string == "NOC_REG_WRITE_ERR" or id_string == "NOC_REG_WRITE" or id_string == "NOC_READ_RSP" or id_string == "NOC_READ_RSP_ERR"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_mode = (lower_data64 >> 48) & 0xF
                log_addr = ((upper_data64 & 0xFFFFF) << 12) | (lower_data64 >> 52)
                return ret_string + "from tile: {}, mode: {:d}, local addr: {:#010x}".format(modid_to_tile(log_modid), log_mode, log_addr)

            if (id_string == "NOC_READ_RSP_DONE"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_error = (lower_data64 >> 48) & 0x1F
                return ret_string + "from tile: {}, error: {}".format(modid_to_tile(log_modid), TCUError.print_error(log_error))

            if (id_string == "NOC_WRITE"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_mode = (lower_data64 >> 48) & 0xF
                log_addr = ((upper_data64 & 0xFFFFF) << 12) | (lower_data64 >> 52)
                return ret_string + "from tile: {}, mode: {:d}, local addr: {:#010x}".format(modid_to_tile(log_modid), log_mode, log_addr)

            if (id_string == "NOC_READ_ERR" or id_string == "NOC_READ"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_mode = (lower_data64 >> 48) & 0xF
                log_addr = ((upper_data64 & 0xFFFFF) << 12) | (lower_data64 >> 52)
                log_size = upper_data64 >> 20
                return ret_string + "from tile: {}, mode: {:d}, local addr: {:#010x} size: {:d}".format(modid_to_tile(log_modid), log_mode, log_addr, log_size)

        #version = 4
        else:
            if (id_string == "NOC_READ_RSP" or id_string == "NOC_READ_RSP_ERR"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_addr = ((upper_data64 & 0xFFFF) << 16) | (lower_data64 >> 48)
                return ret_string + "from tile: {}, local addr: {:#010x}".format(modid_to_tile(log_modid), log_addr)

            if (id_string == "NOC_READ_RSP_DONE"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_error = (lower_data64 >> 48) & 0x3F
                return ret_string + "from tile: {}, error: {}".format(modid_to_tile(log_modid), TCUError.print_error(log_error))

            if (id_string == "NOC_WRITE" or id_string == "NOC_READ" or id_string == "NOC_PMP_WRITE" or id_string == "NOC_PMP_READ"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_addr = ((upper_data64 & 0xFFFF) << 16) | (lower_data64 >> 48)
                log_size = (upper_data64 >> 16) & 0xFFFFFFFF
                return ret_string + "from tile: {}, addr: {:#010x}, size: {:d}".format(modid_to_tile(log_modid), log_addr, log_size)

        #NoC received msg
        if (id_string == "NOC_MSG" or id_string == "NOC_MSG_INV"):
            log_modid = (lower_data64 >> 40) & 0xFF
            log_ep = (lower_data64 >> 48) & 0xFFFF
            return ret_string + "from tile: {}, recv-ep: {:d}".format(modid_to_tile(log_modid), log_ep)

        #NoC received write ACK
        if (id_string == "NOC_WRITE_ACK"):
            log_modid = (lower_data64 >> 40) & 0xFF
            log_addr = ((upper_data64 & 0xFFFF) << 16) | ((lower_data64 >> 48) & 0xFFFF)
            if version < 4:
                log_size = (upper_data64 >> 16) & 0xFFFFFFFF
                return ret_string + "from tile: {}, addr: {:#010x}, size: {:d}".format(modid_to_tile(log_modid), log_addr, log_size)
            else:
                return ret_string + "from tile: {}, addr: {:#010x}".format(modid_to_tile(log_modid), log_addr)

        #NoC received msg ACK or error packet
        if version < 4:
            if (id_string == "NOC_MSG_ACK" or id_string == "NOC_ACK_ERR"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_error = (lower_data64 >> 48) & 0x1F
                return ret_string + "from tile: {}, error: {}".format(modid_to_tile(log_modid), TCUError.print_error(log_error))
        else:
            if (id_string == "NOC_MSG_ACK"):
                log_modid = (lower_data64 >> 40) & 0xFF
                log_ep = lower_data64 >> 48
                return ret_string + "from tile: {}, send-ep: {:d}".format(modid_to_tile(log_modid), log_ep)

            if (id_string == "NOC_ACK_ERR"):
                log_error = (lower_data64 >> 40) & 0x3F
                return ret_string + "error: {}".format(TCUError.print_error(log_error))

        #only version < 4
        if (id_string == "NOC_ERROR" or id_string == "NOC_ERROR_UNEXP"):
            log_modid = (lower_data64 >> 40) & 0xFF
            log_addr = ((upper_data64 & 0xFFFF) << 16) | ((lower_data64 >> 48) & 0xFFFF)
            log_error = (upper_data64 >> 16) & 0x1F
            return ret_string + "from tile: {}, addr: {:#010x}, error: {}".format(modid_to_tile(log_modid), log_addr, TCUError.print_error(log_error))

        #NoC received packet with invalid data
        #only version < 4
        if (id_string == "NOC_INVMODE" or id_string == "NOC_INVFLIT"):
            log_modid = (lower_data64 >> 40) & 0xFF
            log_mode = (lower_data64 >> 48) & 0xF
            log_addr = ((upper_data64 & 0xFFFFF) << 12) | (lower_data64 >> 52)
            log_burst_flag = (upper_data64 >> 20) & 0x1
            log_burst_length = (lower_data64 >> 21) & 0xFFFF
            return ret_string + "from tile: {}, mode: {:d}, addr: {:#010x}, burst flag: {}, burst length: {:d}".format(modid_to_tile(log_modid), log_mode, log_addr, log_burst_flag, log_burst_length)

        #priv. cmds
        #invalidate page
        if (id_string == "CMD_PRIV_INV_PAGE"):
            log_actid = (lower_data64 >> 40) & 0xFFFF
            log_virt = ((upper_data64 & (0xFFFFFFFFFFF if version == 1 else 0xFFF)) << 8) | (lower_data64 >> 56)
            return ret_string + "actid: {:#x}, virt. page: {:#016x}".format(log_actid, log_virt)

        #insert TLB
        if (id_string == "CMD_PRIV_INS_TLB"):
            log_actid = (lower_data64 >> 40) & 0xFFFF
            log_virt = ((upper_data64 & 0xFFF) << 8) | (lower_data64 >> 56)
            log_phys = (upper_data64 >> 12) & 0xFFFFF
            return ret_string + "actid: {:#x}, virt. page: {:#07x}, phys. page: {:#07x}".format(log_actid, log_virt, log_phys)

        #xchg_act
        if version < 4:
            #act=id+msgs
            if (id_string == "CMD_PRIV_XCHG_VPE"):
                log_curact = ((upper_data64 & 0xFF) << 24) | (lower_data64 >> 40)
                log_xchgact = (upper_data64 >> 8) & 0xFFFFFFFF
                return ret_string + "cur_act: {:#x}, xchg_act: {:#x}".format(log_curact, log_xchgact)
        else:
            if (id_string == "CMD_PRIV_XCHG_ACT"):
                log_curactid = (lower_data64 >> 40) & 0xFFFF
                log_xchgactid = ((upper_data64 & 0xFF) << 8) | (lower_data64 >> 56)
                return ret_string + "cur_actid: {:#x}, xchg_actid: {:#x}".format(log_curactid, log_xchgactid)

        #timer
        if (id_string == "CMD_PRIV_SET_TIMER"):
            log_time = ((upper_data64 & 0xFF) << 24) | (lower_data64 >> 40)
            return ret_string + "time: {:d}".format(log_time)

        if (id_string == "CMD_PRIV_ABORT"):
            log_cmd = (lower_data64 >> 40) & 0xF
            return ret_string + "current cmd opcode: {:d}".format(log_cmd)

        #finish
        if (id_string == "CMD_PRIV_FINISH"):
            log_error = (lower_data64 >> 40) & 0x3F
            return ret_string + "error: {}".format(TCUError.print_error(log_error))

        #CU request
        if (id_string == "PRIV_CU_REQ_FORMSG"):
            log_actid = (lower_data64 >> 40) & 0xFFFF
            log_ep = ((upper_data64 & 0xFF) << 8) | (lower_data64 >> 56)
            return ret_string + "actid: {:#x}, ep: {:d}".format(log_actid, log_ep)

        if (id_string == "PRIV_CU_REQ_PMPFAIL"):
            log_write = (lower_data64 >> 40) & 0x1
            if version < 4:
                log_error = (lower_data64 >> 41) & 0x1F
                log_addr = ((upper_data64 & 0x2FFF) << 18) | (lower_data64 >> 46)
            else:
                log_error = (lower_data64 >> 41) & 0x3F
                log_addr = ((upper_data64 & 0x7FFF) << 17) | (lower_data64 >> 47)
            return ret_string + "write: {}, error: {}, addr: {:#x}".format(log_write, TCUError.print_error(log_error), log_addr)

        #TLB write
        if (id_string == "PRIV_TLB_WRITE_ENTRY"):
            log_tlb_actid = (lower_data64 >> 40) & 0xFFFF
            log_tlb_virtpage = ((upper_data64 & 0xFFF) << 8) | (lower_data64 >> 56)
            log_tlb_physpage = (upper_data64 >> 12) & 0xFFFFF
            log_tlb_flags = (upper_data64 >> 32) & 0x7
            return ret_string + "actid: {:#x}, virt. page: {:#07x}, phys. page: {:#07x}, flags: {}".format(log_tlb_actid, log_tlb_virtpage, log_tlb_physpage, Flags.flags_bits2str(log_tlb_flags))

        #TLB read
        if (id_string == "PRIV_TLB_READ_ENTRY"):
            log_tlb_actid = (lower_data64 >> 40) & 0xFFFF
            log_tlb_virtpage = ((upper_data64 & 0xFFF) << 8) | (lower_data64 >> 56)
            return ret_string + "actid: {:#x}, virt. page: {:#07x}".format(log_tlb_actid, log_tlb_virtpage)

        #TLB invalidate page
        if (id_string == "PRIV_TLB_DEL_ENTRY"):
            log_tlb_actid = (lower_data64 >> 40) & 0xFFFF
            log_tlb_virtpage = ((upper_data64 & (0xFFFFFFFFFFF if version == 1 else 0xFFF)) << 8) | (lower_data64 >> 56)
            return ret_string + "actid: {:#x}, virt. page: {:#016x}".format(log_tlb_actid, log_tlb_virtpage)

        #reg CUR_ACT has changed its value
        if (id_string == "PRIV_CUR_ACT_CHANGE"):
            log_new_cur_act = ((upper_data64 & 0xFF) << 24) | (lower_data64 >> 40)
            log_old_cur_act = (upper_data64 >> 8) & 0xFFFFFFFF
            return ret_string + "old cur_act: {:#x}, new cur_act: {:#x}".format(log_old_cur_act, log_new_cur_act)

        #PMP: access from core not allowed
        if (id_string == "PMP_ACCESS_DENIED"):
            log_flags = (lower_data64 >> 40) & 0xF
            log_addr = ((upper_data64 & 0xFFF) << 20) | (lower_data64 >> 44)
            log_size = (upper_data64 >> 12) & 0xFFFF
            return ret_string + "flags: {}, addr: {:#010x}, size: {:d}".format(Flags.flags_bits2str(log_flags), log_addr, log_size)

        #only version 4
        if (id_string == "EXCLREG_ACCESS_DENIED"):
            log_modid = (lower_data64 >> 40) & 0xFF
            log_gen = (lower_data64 >> 48) & 0xFF
            log_addr = ((upper_data64 & 0xFFFFFF) << 8) | ((lower_data64 >> 56) & 0xFF)
            log_size = (upper_data64 >> 24) & 0xFFFFFFFF
            log_error = (upper_data64 >> 56) & 0x3F
            return ret_string + "from tile: {}, gen: {:d}, addr: {:#010x}, size: {:d}, error: {}".format(modid_to_tile(log_modid), log_gen, log_addr, log_size, TCUError.print_error(log_error))

        #only version 4
        if (id_string == "DBG_PRINT"):
            log_size = ((upper_data64 & 0xFF) << 24) | (lower_data64 >> 40)
            return ret_string + "size: {} bytes".format(log_size)

        return ret_string

    def get_tcu_log(version, log_id):
        if version < 4:
            len_log_id = len(LOG.LOG_ID_V3)
            LOG_ID = LOG.LOG_ID_V3
        else:
            len_log_id = len(LOG.LOG_ID_V4)
            LOG_ID = LOG.LOG_ID_V4
        if (log_id >= len_log_id):
            return "UNDEFINED"
        return LOG_ID[log_id]
