mod com;
mod proto;

use com::{Communicator, FPGAModule};
use cpython::exc::TypeError;
use cpython::PyErr;
use cpython::{py_fn, py_module_initializer, PyBytes, PyResult, Python};
use lazy_static::lazy_static;
use log::{info, logger};
use simplelog::{
    ColorChoice, CombinedLogger, Config, LevelFilter, SharedLogger, TermLogger, TerminalMode,
    WriteLogger,
};
use std::env;
use std::fs::{create_dir, File};
use std::io::BufWriter;
use std::str::FromStr;
use std::sync::Mutex;
use std::time::Duration;

use crate::proto::{ARQProtocol, NoCProtocol, TCUv4Protocol};

py_module_initializer!(nocrw, |py, m| {
    m.add(
        py,
        "connect",
        py_fn!(
            py,
            connect(fpga_ip: &str, fpga_port: u16, chip_id: u8, tcu_major: u8, reset: bool)
        ),
    )?;

    m.add(
        py,
        "read_bytes",
        py_fn!(py, read_bytes(chip_id: u8, mod_id: u8, addr: u32, len: u32)),
    )?;

    m.add(
        py,
        "read8b_nocarq",
        py_fn!(py, read8b_nocarq(chip_id: u8, mod_id: u8, addr: u32)),
    )?;

    m.add(
        py,
        "write_bytes",
        py_fn!(
            py,
            write_bytes(chip_id: u8, mod_id: u8, addr: u32, b: &PyBytes, burst: bool)
        ),
    )?;

    m.add(
        py,
        "write8b_nocarq",
        py_fn!(
            py,
            write8b_nocarq(chip_id: u8, mod_id: u8, addr: u32, b: &PyBytes)
        ),
    )?;

    m.add(
        py,
        "send_bytes",
        py_fn!(
            py,
            send_bytes(version: u8, chip_id: u8, mod_id: u8, ep: u16, b: &PyBytes)
        ),
    )?;

    m.add(
        py,
        "receive_bytes",
        py_fn!(py, receive_bytes(timeout_ns: u64)),
    )?;
    Ok(())
});

#[derive(Default)]
struct LogGuard {}

impl Drop for LogGuard {
    fn drop(&mut self) {
        logger().flush();
    }
}

lazy_static! {
    static ref COM: Mutex<Option<Communicator>> = Mutex::new(None);
}

fn log_level(env_var: &str, def: LevelFilter) -> LevelFilter {
    match env::var(env_var) {
        Ok(log) => LevelFilter::from_str(&log).unwrap(),
        Err(_) => def,
    }
}

fn do_connect(fpga_ip: &str, fpga_port: u16, chip_id: u8, tcu_major: u8, reset: bool) -> std::io::Result<()> {
    // ensure that the log directory exists
    create_dir("log").ok();

    // log to stderr and to file, controlled via env variables RUST_LOG and RUST_FILE_LOG
    let term_level = log_level("RUST_LOG", LevelFilter::Warn);
    let file_level = log_level("RUST_FILE_LOG", LevelFilter::Info);
    let mut loggers: Vec<Box<dyn SharedLogger + 'static>> = vec![];
    loggers.push(WriteLogger::new(
        file_level,
        Config::default(),
        BufWriter::new(File::create("log/ethernet.log")?),
    ));
    loggers.push(TermLogger::new(
        term_level,
        Config::default(),
        TerminalMode::Stderr,
        ColorChoice::Always,
    ));
    CombinedLogger::init(loggers).unwrap();

    info!("connect(fpga_ip={}, fpga_port={})", fpga_ip, fpga_port);
    
    let proto = if tcu_major < 4 {
        Box::new(ARQProtocol) as Box<dyn NoCProtocol>
    } else {
        Box::new(TCUv4Protocol) as Box<dyn NoCProtocol>
    };
    let mut com = Communicator::new(fpga_ip, fpga_port, proto)?;
    if reset {
        info!("Reset FPGA...");
        com.fpga_reset(chip_id)?;
    }
    com.self_test()?;
    *COM.lock().unwrap() = Some(com);
    Ok(())
}

fn connect(
    py: Python<'_>,
    fpga_ip: &str,
    fpga_port: u16,
    chip_id: u8,
    tcu_major: u8,
    reset: bool,
) -> PyResult<u64> {
    assert!(COM.lock().unwrap().is_none());

    let _g = LogGuard::default();

    do_connect(fpga_ip, fpga_port, chip_id, tcu_major, reset)
        .map(|_| 0)
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("connect failed: {}", e)))
}

fn read_bytes(py: Python<'_>, chip_id: u8, mod_id: u8, addr: u32, len: u32) -> PyResult<PyBytes> {
    info!(
        "read_bytes(chip_id={}, mod_id={}, addr={:#x}, len={})",
        chip_id, mod_id, addr, len
    );

    let _g = LogGuard::default();

    let mut guard = COM.lock().unwrap();
    let com = guard.as_mut().unwrap();
    com.read(FPGAModule::new(chip_id, mod_id), addr, len as usize, false)
        .map(|bytes| PyBytes::new(py, &bytes))
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("read_bytes failed: {}", e)))
}

fn read8b_nocarq(py: Python<'_>, chip_id: u8, mod_id: u8, addr: u32) -> PyResult<PyBytes> {
    info!(
        "read8b_nocarq(chip_id={}, mod_id={}, addr={:#x})",
        chip_id, mod_id, addr
    );

    let _g = LogGuard::default();

    let mut guard = COM.lock().unwrap();
    let com = guard.as_mut().unwrap();
    com.read(FPGAModule::new(chip_id, mod_id), addr, 8, true)
        .map(|bytes| PyBytes::new(py, &bytes))
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("read8b_nocarq failed: {}", e)))
}

fn write_bytes(
    py: Python<'_>,
    chip_id: u8,
    mod_id: u8,
    addr: u32,
    b: &PyBytes,
    burst: bool,
) -> PyResult<u64> {
    info!(
        "write_bytes(chip_id={}, mod_id={}, addr={:#x}, len={}, burst={})",
        chip_id,
        mod_id,
        addr,
        b.data(py).len(),
        burst,
    );

    let _g = LogGuard::default();

    let mut guard = COM.lock().unwrap();
    let com = guard.as_mut().unwrap();
    let res = if burst {
        com.write_burst(FPGAModule::new(chip_id, mod_id), addr, b.data(py))
    }
    else {
        com.write_noburst(FPGAModule::new(chip_id, mod_id), addr, b.data(py), false)
    };

    res.map(|_| 0)
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("write_bytes failed: {}", e)))
}

fn write8b_nocarq(
    py: Python<'_>,
    chip_id: u8,
    mod_id: u8,
    addr: u32,
    b: &PyBytes,
) -> PyResult<u64> {
    info!(
        "write8b_nocarq(chip_id={}, mod_id={}, addr={:#x}, len={})",
        chip_id,
        mod_id,
        addr,
        b.data(py).len(),
    );

    let _g = LogGuard::default();

    let mut guard = COM.lock().unwrap();
    let com = guard.as_mut().unwrap();
    let res = com.write_noburst(FPGAModule::new(chip_id, mod_id), addr, b.data(py), true);

    res.map(|_| 0)
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("write8b_nocarq failed: {}", e)))
}

fn send_bytes(
    py: Python<'_>,
    version: u8,
    chip_id: u8,
    mod_id: u8,
    ep: u16,
    b: &PyBytes,
) -> PyResult<u64> {
    info!(
        "send_bytes(version={}, chip_id={}, mod_id={}, ep={}, len={})",
        version,
        chip_id,
        mod_id,
        ep,
        b.data(py).len(),
    );

    let _g = LogGuard::default();

    let mut guard = COM.lock().unwrap();
    let com = guard.as_mut().unwrap();
    let res = com.send_bytes(version, FPGAModule::new(chip_id, mod_id), ep, b.data(py));

    res.map(|_| 0)
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("send_bytes failed: {}", e)))
}

fn receive_bytes(py: Python<'_>, timeout_ns: u64) -> PyResult<PyBytes> {
    info!("receive_bytes(timeout={}ns)", timeout_ns);

    let _g = LogGuard::default();

    let mut guard = COM.lock().unwrap();
    let com = guard.as_mut().unwrap();
    com.receive(Duration::from_nanos(timeout_ns))
        .map(|payload| PyBytes::new(py, &payload))
        .map_err(|e| PyErr::new::<TypeError, _>(py, format!("receive_bytes failed: {}", e)))
}
