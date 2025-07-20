use log::{debug, error};
use num_enum::{IntoPrimitive, TryFromPrimitive};
use socket2::{self, Domain, Protocol, SockAddr, Socket};
use std::cmp;
use std::collections::VecDeque;
use std::convert::TryFrom;
use std::fmt;
use std::io::{Error, ErrorKind, Result};
use std::mem::{transmute, MaybeUninit};
use std::net::{IpAddr, SocketAddr};
use std::thread;
use std::time::Duration;

const ETH_MOD_ID: u8 = 0x05;
const HOST_MOD: FPGAModule = FPGAModule::new(0x3F, 0x05);

const NOC_PACKET_LEN: usize = 18;
const UDP_PAYLOAD_LEN: usize = 1472;

const BYTES_PER_BURST_PACKET: usize = 16;
const BYTES_PER_PACKET: usize = 8;

const MAX_SELF_TEST_RETRIES: usize = 100;

// TODO using 2047 leads to an EAGAIN error for recv_from after about 50KB. using 1024+512 seems to
// work fine and reaches a sufficiently high data rate.
const MAX_READ_REQ_LEN: usize = (1024 + 512) * BYTES_PER_BURST_PACKET;
const MAX_WRITE_BURST_LEN: usize = 255 * BYTES_PER_BURST_PACKET;
const MAX_SEND_BURST_LEN: usize = 128 * BYTES_PER_BURST_PACKET;

const READ_TIMEOUT: Duration = Duration::from_secs(1);
const MAX_READ_RETRIES: usize = 3;

#[repr(u8)]
#[derive(Debug, Eq, PartialEq, IntoPrimitive, TryFromPrimitive, Copy, Clone)]
enum Mode {
    DMARead        = 0,
    DMAResp        = 1,
    DMAWrite       = 2,
    DMAAck         = 3,
    TCUMsg         = 4,
    TCUMsgAck      = 5,
    Error          = 15
}

#[derive(Copy, Clone, Eq, PartialEq)]
pub struct FPGAModule {
    pub chip_id: u8,
    pub mod_id: u8,
}

impl FPGAModule {
    pub const fn new(chip_id: u8, mod_id: u8) -> Self {
        Self { chip_id, mod_id }
    }
}

impl fmt::Display for FPGAModule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "(chip={}, mod={})", self.chip_id, self.mod_id)
    }
}

pub struct Communicator {
    addr: SockAddr,
    sock: Socket,
    next_req_id: u32,
    send_buf: Vec<u8>,
    burst: Option<(u8, bool)>,
    received_pkts: VecDeque<Vec<u8>>,
}

enum NocPacket<'b> {
    Normal((FPGAModule, Mode, u32, &'b [u8])),
    Burst(&'b [u8]),
}

impl Communicator {
    pub fn new(fpga_ip: &str, fpga_port: u16) -> Result<Self> {
        let sock = Socket::new(Domain::IPV4, socket2::Type::DGRAM, Some(Protocol::UDP))?;
        let addr = "0.0.0.0:".to_string() + &fpga_port.to_string();
        sock.bind(&addr.parse::<SocketAddr>().unwrap().into())?;

        sock.set_read_timeout(Some(READ_TIMEOUT))?;

        Ok(Self {
            addr: SockAddr::from(SocketAddr::new(
                IpAddr::V4(fpga_ip.parse().unwrap()),
                fpga_port,
            )),
            sock,
            next_req_id: 0,
            send_buf: Vec::with_capacity(UDP_PAYLOAD_LEN),
            burst: None,
            received_pkts: VecDeque::new(),
        })
    }

    pub fn self_test(&mut self) -> Result<()> {
        let test_data = [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xFF];
        // use an offset that nobody else should use; notice the alignment
        self.write_noburst(HOST_MOD, 0xDEAD_BEE0, &test_data)?;

        let mut buf: [MaybeUninit<u8>; UDP_PAYLOAD_LEN] = [MaybeUninit::uninit(); UDP_PAYLOAD_LEN];

        // try multiple times, because PEs might still be busy with sending prints to the ETH
        let mut retries = 0;
        while retries < MAX_SELF_TEST_RETRIES {
            let (size, _) = self.sock.recv_from(&mut buf)?;
            if size < NOC_PACKET_LEN {
                continue;
            }

            // safety: now we can assume that buf[0..size] is initialized
            let recv_buf: &[u8] = unsafe { transmute(&buf[0..size]) };

            let old_burst = self.burst;
            let noc_packet = self.decode_packet(recv_buf)?;
            match noc_packet {
                NocPacket::Normal((src, mode, off, data)) => {
                    // we assume that nobody is writing to this offset, except for the self test
                    if off == 0xDEAD_BEE0 {
                        assert!(mode == Mode::DMAWrite);
                        assert!(self.burst.is_none());
                        assert!(src == HOST_MOD);
                        assert!(data.iter().rev().eq(test_data.iter()));
                        return Ok(());
                    }
                },
                _ => {},
            }

            self.burst = old_burst;
            retries += 1;
        }

        Err(Error::new(ErrorKind::TimedOut, "no self test response"))
    }

    pub fn fpga_reset(&mut self, chip_id: u8) -> Result<()> {
        let reset_data: [u8; 8] = [1, 0, 0, 0, 0, 0, 0, 0];
        self.write_noburst(
            FPGAModule::new(chip_id, ETH_MOD_ID),
            0xF0003028,
            &reset_data,
        )?;

        //need some time to get FPGA restarted
        let wait_sec = Duration::from_secs(5);
        thread::sleep(wait_sec);

        Ok(())
    }

    pub fn send_bytes(
        &mut self,
        version: u8,
        target: FPGAModule,
        ep: u16,
        data: &[u8],
    ) -> Result<()> {
        #[repr(C, packed)]
        struct MessageHeader {
            other: u32,
            sender_ep: u16,
            reply_ep: u16,
            // we don't care about the rest and it differs between v0 and v1
            _dummy: [u64; 3],
        }

        let sender_tile = ((HOST_MOD.chip_id as u32) << 8) | HOST_MOD.mod_id as u32;
        let header = MessageHeader {
            other: (data.len() as u32) << 19 | (sender_tile << 5) | (4 << 1),
            sender_ep: 0xFFFFu16.to_le(),
            reply_ep: 0xFFFFu16.to_le(),
            _dummy: [0; 3],
        };
        let header_bytes = unsafe {
            std::slice::from_raw_parts(
                &header as *const _ as *const u8,
                std::mem::size_of::<MessageHeader>(),
            )
        };

        // write initial NoC packet that defines the burst length
        assert!(data.len() <= MAX_SEND_BURST_LEN);
        let header_length = if version == 0 { 16 } else { 32 };
        let header_packets = header_length as u64 / 16 as u64;
        // the first flit is always the header
        let word_count = header_packets
            + ((data.len() + BYTES_PER_BURST_PACKET - 1) / BYTES_PER_BURST_PACKET) as u64;
        let word_count_bytes = word_count.to_le_bytes();
        // TODO change bsel according to data.len()
        let noc_packet = encode_packet(
            target,
            true,
            0xFF,
            ep as u32,
            &word_count_bytes,
            Mode::TCUMsg,
        );
        self.append_packet(&noc_packet)?;

        // append message header
        let mut rem_header = &header_bytes[0..header_length];
        while rem_header.len() > 0 {
            let pkt =
                encode_packet_burst(rem_header.len() > 16 || data.len() > 0, &rem_header[0..16]);
            self.append_packet(&pkt)?;
            rem_header = &rem_header[16..];
        }

        // append data
        let mut pos = 0;
        while pos < data.len() {
            let not_last = pos + BYTES_PER_BURST_PACKET < data.len();
            // pad last packet with zeros, if required
            let noc_packet = if !not_last && pos + BYTES_PER_BURST_PACKET > data.len() {
                let mut padded_data = data[pos..].to_vec();
                for _ in 0..(BYTES_PER_BURST_PACKET - (data.len() - pos)) {
                    padded_data.push(0);
                }
                encode_packet_burst(not_last, &padded_data)
            }
            else {
                encode_packet_burst(not_last, &data[pos..])
            };
            self.append_packet(&noc_packet)?;

            pos += BYTES_PER_BURST_PACKET;
        }

        self.flush_packets()
    }

    pub fn receive(&mut self, timeout: Duration) -> Result<Vec<u8>> {
        // set custom timeout
        self.sock.set_read_timeout(Some(timeout))?;
        let res = self.do_receive();
        // restore default timeout
        self.sock.set_read_timeout(Some(READ_TIMEOUT)).ok();
        res
    }

    fn do_receive(&mut self) -> Result<Vec<u8>> {
        // either take a packet from our receive queue
        let (buf, size) = if let Some(pkt) = self.received_pkts.pop_front() {
            let size = pkt.len();
            (pkt, size)
        }
        // or receive a new one
        else {
            let mut buf: Vec<MaybeUninit<u8>> = vec![MaybeUninit::uninit(); UDP_PAYLOAD_LEN];
            let (size, _) = self.sock.recv_from(&mut buf[..])?;
            assert!(size >= NOC_PACKET_LEN);
            // safety: buf[0..size] is now initialized, so resize it and transmute
            buf.resize(size, MaybeUninit::uninit());
            let buf: Vec<u8> = unsafe { transmute(buf) };
            (buf, size)
        };

        let mut pos = 0;
        let mut res = vec![];
        while pos + NOC_PACKET_LEN <= size {
            let noc_packet = self.decode_packet(&buf[pos..])?;
            match noc_packet {
                NocPacket::Normal((src, mode, off, data)) => {
                    if mode == Mode::DMAAck {
                        debug!("Received DMAAck from {} for addr {:#x}", src, off);
                        pos += NOC_PACKET_LEN;
                        continue;
                    }

                    // ignore other packets
                    if mode != Mode::DMAWrite {
                        debug!("Ignoring packet with mode {:?}", mode);
                        pos += NOC_PACKET_LEN;
                        continue;
                    }

                    if self.burst.is_some() {
                        debug!("Received burst-start from {} at offset {:#x}", src, off);
                    }
                    else {
                        debug!(
                            "Received packet from {} at offset {:#x}: {:02x?}",
                            src, off, data
                        );
                        res.extend(data.iter().rev());
                    }
                },
                NocPacket::Burst(data) => {
                    res.extend(data.iter().rev());
                },
            }
            pos += NOC_PACKET_LEN;
        }

        Ok(res)
    }

    pub fn read(
        &mut self,
        target: FPGAModule,
        mut addr: u32,
        mut len: usize
    ) -> Result<Vec<u8>> {
        let mut buf: [MaybeUninit<u8>; UDP_PAYLOAD_LEN] = [MaybeUninit::uninit(); UDP_PAYLOAD_LEN];
        let mut res = Vec::with_capacity(len);

        let mut retries = 0;
        let mut last_addr = addr;
        while len > 0 {
            match self.read_single(&mut buf, &mut res, target, Mode::DMARead, addr, len) {
                Err(e) => {
                    error!("read request failed: {}", e);

                    // receive all packets the FPGA sends us, with a timeout of 100ms
                    self.sock
                        .set_read_timeout(Some(Duration::from_millis(100)))?;
                    while self.sock.recv_from(&mut buf[..]).is_ok() {}
                    self.sock.set_read_timeout(Some(READ_TIMEOUT)).ok();

                    // give up if the error persists for the same address
                    if last_addr == addr {
                        retries += 1;
                        if retries >= MAX_READ_RETRIES {
                            return Err(e);
                        }
                    }
                    else {
                        retries = 0;
                        last_addr = addr;
                    }
                },
                Ok(amount) => {
                    addr += amount as u32;
                    len -= amount;
                },
            }
        }

        Ok(res)
    }

    fn read_single(
        &mut self,
        buf: &mut [MaybeUninit<u8>],
        res: &mut Vec<u8>,
        target: FPGAModule,
        read_mode: Mode,
        addr: u32,
        len: usize,
    ) -> Result<usize> {
        let mut req_id = self.next_req_id;
        self.next_req_id = self.next_req_id.wrapping_add(1);

        let byte_count = cmp::min(MAX_READ_REQ_LEN, len);
        let byte_count_bytes = ((byte_count as u64) << 32 | req_id as u64).to_le_bytes();
        let noc_packet = encode_packet(target, false, 0xFF, addr, &byte_count_bytes, read_mode);
        self.append_packet(&noc_packet)?;
        self.flush_packets()?;

        let org_len = res.len();
        while res.len() - org_len < byte_count {
            let (size, _) = self.sock.recv_from(&mut buf[..])?;

            // safety: buf[0..size] is now initialized, so resize it and transmute
            let recv_buf: &[u8] = unsafe { transmute(&buf[0..size]) };

            let mut pos = 0;
            'pkt_loop: while pos + NOC_PACKET_LEN <= size {
                let old_burst = self.burst;
                let noc_packet = self.decode_packet(&recv_buf[pos..])?;

                match noc_packet {
                    NocPacket::Normal((src, mode, off, data)) => {
                        if mode == Mode::DMAWrite {
                            debug!("Keeping packet with mode {:?} for later", mode);
                            // keep the packet for later and go to the next UDP packet
                            self.received_pkts.push_back(recv_buf[0..size].to_vec());
                            self.burst = old_burst;
                            pos = size;
                            break 'pkt_loop;
                        }

                        if mode == Mode::DMAAck {
                            debug!("Received DMAAck from {} for addr {:#x}", src, off);
                            pos += NOC_PACKET_LEN;
                            continue;
                        }

                        // ignore other packets; TODO support messages
                        if mode != Mode::DMAResp {
                            debug!("Ignoring packet with mode {:?}", mode);
                            pos += NOC_PACKET_LEN;
                            continue;
                        }

                        // sometimes we get a delayed response for an earlier request; stop here
                        if off != req_id {
                            debug!(
                                "Received packet with unexpected offset {:#x} (expected {:#x})",
                                off, req_id
                            );
                            return Err(Error::from(ErrorKind::InvalidData));
                        }
                        else if self.burst.is_some() {
                            debug!("Received burst-start from {} at offset {:#x}", src, off);
                        }
                        else {
                            debug!(
                                "Received packet from {} at offset {:#x}: {:02x?}",
                                src, off, data
                            );
                            res.extend(data.iter().rev());
                            req_id = req_id.wrapping_add(data.len() as u32);
                        }
                    },
                    NocPacket::Burst(data) => {
                        res.extend(data.iter().rev());
                        req_id = req_id.wrapping_add(data.len() as u32);
                    },
                }
                pos += NOC_PACKET_LEN;
            }
            assert!(pos == size);
        }

        assert!(res.len() - org_len == byte_count);
        Ok(res.len() - org_len)
    }

    pub fn write_noburst(
        &mut self,
        target: FPGAModule,
        mut addr: u32,
        data: &[u8]
    ) -> Result<usize> {
        let build_min_packet = |data: &[u8], pos: usize| {
            let mut buf = data[pos..].to_vec();
            // pad remaining data with zeros to reach BYTES_PER_PACKET bytes
            while buf.len() % BYTES_PER_PACKET != 0 {
                buf.push(0);
            }
            buf
        };

        let mut pos = 0;
        let write_mode = Mode::DMAWrite;

        // align it first
        let rem = addr as usize % BYTES_PER_PACKET;
        if rem != 0 {
            let buf = build_min_packet(data, pos);
            let noc_pkt = encode_packet(target, false, 0xFF >> rem, addr, &buf, write_mode);
            self.append_packet(&noc_pkt)?;

            let amount = BYTES_PER_PACKET - rem;
            addr += amount as u32;
            pos += amount;
        }

        // write full and aligned packets
        while pos + BYTES_PER_PACKET <= data.len() {
            let noc_pkt = encode_packet(target, false, 0xFF, addr, &data[pos..], write_mode);
            self.append_packet(&noc_pkt)?;

            addr += BYTES_PER_PACKET as u32;
            pos += BYTES_PER_PACKET;
        }

        // write trailing packet
        if pos < data.len() {
            let buf = build_min_packet(data, pos);
            let rem = data.len() - pos;
            let noc_pkt = encode_packet(
                target,
                false,
                0xFF >> (0x7 - rem),
                addr,
                &buf,
                Mode::DMAWrite,
            );
            self.append_packet(&noc_pkt)?;

            pos = data.len();
        }

        self.flush_packets().map(|_| pos)
    }

    pub fn write_burst(&mut self, target: FPGAModule, mut addr: u32, data: &[u8]) -> Result<usize> {
        let mut pos = 0;
        let mut burst_pos = MAX_WRITE_BURST_LEN;
        while pos + BYTES_PER_BURST_PACKET <= data.len() {
            assert!(addr % 16 == 0); // TODO support other alignments
            if burst_pos >= MAX_WRITE_BURST_LEN {
                // write initial NoC packet that defines the burst length
                let byte_count = cmp::min(MAX_WRITE_BURST_LEN, data.len() - pos);
                let word_count = (byte_count / BYTES_PER_BURST_PACKET) as u64;
                let word_count_bytes = word_count.to_le_bytes();
                let noc_packet = encode_packet(
                    target,
                    true,
                    0xFF,
                    addr,
                    &word_count_bytes,
                    Mode::DMAWrite,
                );
                self.append_packet(&noc_packet)?;
                addr += word_count as u32 * BYTES_PER_BURST_PACKET as u32;
                burst_pos = 0;
            }

            let not_last = burst_pos + (BYTES_PER_BURST_PACKET * 2) <= MAX_WRITE_BURST_LEN
                && (pos + BYTES_PER_BURST_PACKET * 2) <= data.len();
            let noc_packet = encode_packet_burst(not_last, &data[pos..]);
            self.append_packet(&noc_packet)?;

            pos += BYTES_PER_BURST_PACKET;
            burst_pos += BYTES_PER_BURST_PACKET;
        }

        // sent the remaining data without burst, if there is any
        self.write_noburst(target, addr, &data[pos..])
    }

    fn append_packet(&mut self, packet: &[u8]) -> Result<()> {
        if self.send_buf.len() + packet.len() > self.send_buf.capacity() {
            self.flush_packets()?;
        }

        debug!("-> NoC packet: {:02x?}", &packet);
        self.send_buf.extend_from_slice(&packet);
        Ok(())
    }

    fn flush_packets(&mut self) -> Result<()> {
        if !self.send_buf.is_empty() {
            self.sock.send_to(&self.send_buf, &self.addr)?;
            self.send_buf.clear();
        }
        Ok(())
    }

    fn decode_packet<'b>(&mut self, bytes: &'b [u8]) -> Result<NocPacket<'b>> {
        debug!("<- NoC packet: {:02x?}", &bytes[0..18]);
        if let Some((bsel, ref mut first)) = self.burst {
            // bsel[3:0] = addr of first valid byte in first 128-bit burst flit
            // bsel[7:4] = addr of last valid byte in last 128-bit burst flit
            //
            // bsel  | first | last
            // --------------------
            // 0xF   | 0     |  15
            // 0xE   | 1     |  14
            // 0xD   | 2     |  13
            // 0xC   | 3     |  12
            // 0xB   | 4     |  11
            // 0xA   | 5     |  10
            // 0x9   | 6     |  9
            // 0x8   | 7     |  8
            // 0x7   | 8     |  7
            // 0x6   | 9     |  6
            // 0x5   | 10    |  5
            // 0x4   | 11    |  4
            // 0x3   | 12    |  3
            // 0x2   | 13    |  2
            // 0x1   | 14    |  1
            // 0x0   | 15    |  0

            let begin = if bytes[0] == 0 {
                (0xF - (bsel >> 4)) as usize
            }
            else {
                0
            };
            let end = if *first {
                (0xF - (bsel & 0xF)) as usize
            }
            else {
                0
            };

            *first = false;
            if bytes[0] == 0 {
                self.burst = None;
            }

            Ok(NocPacket::Burst(&bytes[2 + begin..18 - end]))
        }
        else {
            let src = FPGAModule::new(bytes[3] >> 2, bytes[2]);
            let addr = (bytes[6] as u32) << 24
                | (bytes[7] as u32) << 16
                | (bytes[8] as u32) << 8
                | bytes[9] as u32;
            if bytes[0] == 1 {
                self.burst = Some((bytes[1], true));
            }
            let mode =
                Mode::try_from(bytes[5] & 0xF).map_err(|_| Error::from(ErrorKind::InvalidData))?;
            let data = if bytes[1] == 0xFF {
                &bytes[10..18]
            }
            else {
                let first = bytes[1].leading_zeros() as usize;
                let last = bytes[1].trailing_zeros() as usize;
                &bytes[10 + first..18 - last]
            };
            Ok(NocPacket::Normal((src, mode, addr, data)))
        }
    }
}

fn encode_packet(
    target: FPGAModule,
    burst: bool,
    bsel: u8,
    addr: u32,
    bytes: &[u8],
    mode: Mode,
) -> [u8; 18] {
    let mode_byte: u8 = mode.into();
    [
        // burst bit
        burst as u8,
        // bsel
        bsel,
        // source and target
        HOST_MOD.mod_id,
        (HOST_MOD.chip_id << 2) | target.mod_id >> 6,
        (target.mod_id << 2) | (target.chip_id >> 4),
        (target.chip_id << 4) | mode_byte,
        // target address
        (addr >> 24) as u8,
        (addr >> 16) as u8,
        (addr >> 8) as u8,
        (addr >> 0) as u8,
        // data
        bytes[7],
        bytes[6],
        bytes[5],
        bytes[4],
        bytes[3],
        bytes[2],
        bytes[1],
        bytes[0],
    ]
}

fn encode_packet_burst(not_last: bool, bytes: &[u8]) -> [u8; 18] {
    [
        // burst bit
        not_last as u8,
        0xFF,
        // data
        bytes[15],
        bytes[14],
        bytes[13],
        bytes[12],
        bytes[11],
        bytes[10],
        bytes[9],
        bytes[8],
        bytes[7],
        bytes[6],
        bytes[5],
        bytes[4],
        bytes[3],
        bytes[2],
        bytes[1],
        bytes[0],
    ]
}
