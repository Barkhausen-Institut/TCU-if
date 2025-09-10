use std::convert::TryFrom;

use num_enum::{IntoPrimitive, TryFromPrimitive};

pub const BYTES_PER_BURST_PACKET: usize = 16;
pub const BYTES_PER_PACKET: usize = 8;

// TODO using 2047 leads to an EAGAIN error for recv_from after about 50KB. using 1024+512 seems to
// work fine and reaches a sufficiently high data rate.
pub const MAX_READ_REQ_LEN: usize = (1024 + 512) * BYTES_PER_BURST_PACKET;
pub const MAX_SEND_BURST_LEN: usize = 128 * BYTES_PER_BURST_PACKET;

#[repr(u8)]
#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub enum Mode {
    Invalid,
    Write,
    WriteARQ,
    Read,
    ReadARQ,
    Message,
    Ack,
    Resp,
}

pub trait NoCProtocol: Send + Sync {
    fn max_write_burst_len(&self) -> usize;
    fn to_noc_mode(&self, mode: Mode) -> u8;
    fn from_noc_mode(&self, mode: u8) -> Mode;
    fn burst_byte(&self, burst: bool, arq: bool) -> u8;
    fn is_burst(&self, bytes: &[u8]) -> bool;
}

#[repr(u8)]
#[derive(Debug, Eq, PartialEq, IntoPrimitive, TryFromPrimitive, Copy, Clone)]
enum ARQMode {
    ReadReq        = 0,
    ReadResp       = 1,
    WritePosted    = 2,
    TCUMsg         = 3,
    TCUAck         = 4,
    ReadReq2       = 5,
    ReadResp2      = 6,
    WritePosted2   = 7,
    Error          = 8,
    ARQAck         = 9,
    ARQReadReq     = 10,
    ARQReadResp    = 11,
    ARQWritePosted = 12,
}

pub struct ARQProtocol;

impl NoCProtocol for ARQProtocol {
    fn max_write_burst_len(&self) -> usize {
        2047 * BYTES_PER_BURST_PACKET
    }

    fn to_noc_mode(&self, mode: Mode) -> u8 {
        match mode {
            Mode::Write => ARQMode::WritePosted as u8,
            Mode::WriteARQ => ARQMode::ARQWritePosted as u8,
            Mode::Read => ARQMode::ReadReq as u8,
            Mode::ReadARQ => ARQMode::ARQReadReq as u8,
            Mode::Message => ARQMode::TCUMsg as u8,
            m => panic!("Tried to convert {:?} to NoC mode", m),
        }
    }

    fn from_noc_mode(&self, mode: u8) -> Mode {
        let noc_mode = ARQMode::try_from(mode).unwrap();
        match noc_mode {
            ARQMode::ReadResp => Mode::Resp,
            ARQMode::ARQReadResp => Mode::Resp,
            ARQMode::WritePosted => Mode::Write,
            ARQMode::TCUMsg => Mode::Message,
            _ => Mode::Invalid,
        }
    }

    fn burst_byte(&self, burst: bool, arq: bool) -> u8 {
        ((burst as u8) << 1) | (arq as u8)
    }

    fn is_burst(&self, bytes: &[u8]) -> bool {
        (bytes[0] >> 1) == 1
    }
}

#[repr(u8)]
#[derive(Debug, Eq, PartialEq, IntoPrimitive, TryFromPrimitive, Copy, Clone)]
enum TCUv4Mode {
    DMARead   = 0,
    DMAResp   = 1,
    DMAWrite  = 2,
    DMAAck    = 3,
    TCUMsg    = 4,
    TCUMsgAck = 5,
    Error     = 15,
}

pub struct TCUv4Protocol;

impl NoCProtocol for TCUv4Protocol {
    fn max_write_burst_len(&self) -> usize {
        255 * BYTES_PER_BURST_PACKET
    }

    fn to_noc_mode(&self, mode: Mode) -> u8 {
        match mode {
            Mode::Write => TCUv4Mode::DMAWrite as u8,
            Mode::Read => TCUv4Mode::DMARead as u8,
            Mode::Message => TCUv4Mode::TCUMsg as u8,
            m => panic!("Tried to convert {:?} to NoC mode", m),
        }
    }

    fn from_noc_mode(&self, mode: u8) -> Mode {
        let noc_mode = TCUv4Mode::try_from(mode).unwrap();
        match noc_mode {
            TCUv4Mode::DMAResp => Mode::Resp,
            TCUv4Mode::DMAAck => Mode::Ack,
            TCUv4Mode::DMAWrite => Mode::Write,
            TCUv4Mode::TCUMsg => Mode::Message,
            _ => Mode::Invalid,
        }
    }

    fn burst_byte(&self, burst: bool, _arq: bool) -> u8 {
        burst as u8
    }

    fn is_burst(&self, bytes: &[u8]) -> bool {
        bytes[0] == 1
    }
}
