use log::{debug, error};
use socket2::{self, Domain, Protocol, SockAddr, Socket};
use std::cmp;
use std::collections::VecDeque;
use std::fmt;
use std::io::{Error, ErrorKind, Result};
use std::mem::{transmute, MaybeUninit};
use std::net::{IpAddr, SocketAddr};
use std::thread;
use std::time::Duration;

use crate::proto::{
    Mode, NoCProtocol, BYTES_PER_BURST_PACKET, BYTES_PER_PACKET, MAX_READ_REQ_LEN,
    MAX_SEND_BURST_LEN,
};

const ETH_MOD_ID: u8 = 0x05;
const HOST_MOD: FPGAModule = FPGAModule::new(0x3F, 0x05);

const NOC_PACKET_LEN: usize = 18;
const UDP_PAYLOAD_LEN: usize = 1472;

const MAX_SELF_TEST_RETRIES: usize = 100;

const READ_TIMEOUT: Duration = Duration::from_secs(1);
const MAX_READ_RETRIES: usize = 3;

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
    proto: Box<dyn NoCProtocol>,
    next_req_id: u32,
    send_buf: Vec<u8>,
    burst: Option<(u8, bool)>,
    received_pkts: VecDeque<Vec<u8>>,
}

enum NocPacket<'b> {
    Normal((FPGAModule, u8, u32, &'b [u8])),
    Burst(&'b [u8]),
}

impl Communicator {
    pub fn new(fpga_ip: &str, fpga_port: u16, proto: Box<dyn NoCProtocol>) -> Result<Self> {
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
            proto,
            next_req_id: 0,
            send_buf: Vec::with_capacity(UDP_PAYLOAD_LEN),
            burst: None,
            received_pkts: VecDeque::new(),
        })
    }

    pub fn self_test(&mut self) -> Result<()> {
        let test_data = [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xFF];
        // use an offset that nobody else should use; notice the alignment
        self.write_noburst(HOST_MOD, 0xDEAD_BEE0, &test_data, false)?;

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
                        assert!(mode == self.proto.to_noc_mode(Mode::Write));
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
            false,
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
            &self.proto,
            target,
            true,
            0xFF,
            ep as u32,
            &word_count_bytes,
            self.proto.to_noc_mode(Mode::Message),
        );
        self.append_packet(&noc_packet)?;

        // append message header
        let mut rem_header = &header_bytes[0..header_length];
        while rem_header.len() > 0 {
            let pkt =
                encode_packet_burst(&self.proto, rem_header.len() > 16 || data.len() > 0, &rem_header[0..16]);
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
                encode_packet_burst(&self.proto, not_last, &padded_data)
            }
            else {
                encode_packet_burst(&self.proto, not_last, &data[pos..])
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
                NocPacket::Normal((src, noc_mode, off, data)) => {
                    let mode = self.proto.from_noc_mode(noc_mode);
                    if mode == Mode::Ack {
                        debug!("Received DMAAck from {} for addr {:#x}", src, off);
                        pos += NOC_PACKET_LEN;
                        continue;
                    }

                    // ignore other packets
                    if mode != Mode::Write {
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
        mut len: usize,
        arq: bool,
    ) -> Result<Vec<u8>> {
        let mut buf: [MaybeUninit<u8>; UDP_PAYLOAD_LEN] = [MaybeUninit::uninit(); UDP_PAYLOAD_LEN];
        let mut res = Vec::with_capacity(len);
        let read_mode = if arq { Mode::ReadARQ } else { Mode::Read };

        let mut retries = 0;
        let mut last_addr = addr;
        while len > 0 {
            match self.read_single(&mut buf, &mut res, target, read_mode, addr, len) {
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
        let noc_packet = encode_packet(
            &self.proto,
            target,
            false,
            0xFF,
            addr,
            &byte_count_bytes,
            self.proto.to_noc_mode(read_mode),
        );
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
                    NocPacket::Normal((src, noc_mode, off, data)) => {
                        let mode = self.proto.from_noc_mode(noc_mode);
                        if mode == Mode::Write {
                            debug!("Keeping packet with mode {:?} for later", mode);
                            // keep the packet for later and go to the next UDP packet
                            self.received_pkts.push_back(recv_buf[0..size].to_vec());
                            self.burst = old_burst;
                            pos = size;
                            break 'pkt_loop;
                        }

                        if mode == Mode::Ack {
                            debug!("Received DMAAck from {} for addr {:#x}", src, off);
                            pos += NOC_PACKET_LEN;
                            continue;
                        }

                        // ignore other packets; TODO support messages
                        if mode != Mode::Resp {
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
        data: &[u8],
        arq: bool,
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
        let arq_write = if arq { Mode::WriteARQ } else { Mode::Write };
        let arq_write = self.proto.to_noc_mode(arq_write);
        let def_write = self.proto.to_noc_mode(Mode::Write);

        // align it first
        let rem = addr as usize % BYTES_PER_PACKET;
        if rem != 0 {
            let buf = build_min_packet(data, pos);
            let noc_pkt = encode_packet(
                &self.proto,
                target,
                false,
                0xFF >> rem,
                addr,
                &buf,
                arq_write,
            );
            self.append_packet(&noc_pkt)?;

            let amount = BYTES_PER_PACKET - rem;
            addr += amount as u32;
            pos += amount;
        }

        // write full and aligned packets
        while pos + BYTES_PER_PACKET <= data.len() {
            let noc_pkt = encode_packet(
                &self.proto,
                target,
                false,
                0xFF,
                addr,
                &data[pos..],
                arq_write,
            );
            self.append_packet(&noc_pkt)?;

            addr += BYTES_PER_PACKET as u32;
            pos += BYTES_PER_PACKET;
        }

        // write trailing packet
        if pos < data.len() {
            let buf = build_min_packet(data, pos);
            let rem = data.len() - pos;
            let noc_pkt = encode_packet(
                &self.proto,
                target,
                false,
                0xFF >> (0x7 - rem),
                addr,
                &buf,
                def_write,
            );
            self.append_packet(&noc_pkt)?;

            pos = data.len();
        }

        self.flush_packets().map(|_| pos)
    }

    pub fn write_burst(&mut self, target: FPGAModule, mut addr: u32, data: &[u8]) -> Result<usize> {
        let max_burst_len = self.proto.max_write_burst_len();
        let write_mode = self.proto.to_noc_mode(Mode::Write);

        let mut pos = 0;
        let mut burst_pos = max_burst_len;

        while pos + BYTES_PER_BURST_PACKET <= data.len() {
            assert!(addr % 16 == 0); // TODO support other alignments
            if burst_pos >= max_burst_len {
                // write initial NoC packet that defines the burst length
                let byte_count = cmp::min(max_burst_len, data.len() - pos);
                let word_count = (byte_count / BYTES_PER_BURST_PACKET) as u64;
                let word_count_bytes = word_count.to_le_bytes();
                let noc_packet = encode_packet(
                    &self.proto,
                    target,
                    true,
                    0xFF,
                    addr,
                    &word_count_bytes,
                    write_mode,
                );
                self.append_packet(&noc_packet)?;
                addr += word_count as u32 * BYTES_PER_BURST_PACKET as u32;
                burst_pos = 0;
            }

            let not_last = burst_pos + (BYTES_PER_BURST_PACKET * 2) <= max_burst_len
                && (pos + BYTES_PER_BURST_PACKET * 2) <= data.len();
            let noc_packet = encode_packet_burst(&self.proto, not_last, &data[pos..]);
            self.append_packet(&noc_packet)?;

            pos += BYTES_PER_BURST_PACKET;
            burst_pos += BYTES_PER_BURST_PACKET;
        }

        // sent the remaining data without burst, if there is any
        self.write_noburst(target, addr, &data[pos..], false)
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

            let begin = if !self.proto.is_burst(bytes) {
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
            if !self.proto.is_burst(bytes) {
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
            if self.proto.is_burst(bytes) {
                self.burst = Some((bytes[1], true));
            }
            let mode = bytes[5] & 0xF;
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
    proto: &Box<dyn NoCProtocol>,
    target: FPGAModule,
    burst: bool,
    bsel: u8,
    addr: u32,
    bytes: &[u8],
    mode: u8,
) -> [u8; 18] {
    let mode_byte: u8 = mode.into();
    [
        // burst bit
        proto.burst_byte(burst, false),
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

fn encode_packet_burst(proto: &Box<dyn NoCProtocol>, not_last: bool, bytes: &[u8]) -> [u8; 18] {
    [
        // burst bit
        proto.burst_byte(not_last, false),
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
