//! canboat's node building blocks (ISO 11783-5 address claiming and the
//! standard discovery responses) for nmea2000's `N2KDevice`. Everything is
//! sans-I/O: frames in, frames out, with the caller supplying the clock.
//! Frames are `(prio, pgn, src, dst, data)` tuples.

use canboat::Frame as RsFrame;
use canboat::device::{self, ClaimState, Claimer, Name, ProductInfo};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

type FrameTuple<'py> = (u8, u32, u8, u8, Bound<'py, PyBytes>);

fn frame<'py>(py: Python<'py>, f: &RsFrame) -> FrameTuple<'py> {
    (f.prio, f.pgn, f.src, f.dst, PyBytes::new(py, &f.data))
}

fn frames<'py>(py: Python<'py>, fs: &[RsFrame]) -> Vec<FrameTuple<'py>> {
    fs.iter().map(|f| frame(py, f)).collect()
}

/// The 64-bit ISO NAME for a node's identity.
#[pyfunction]
#[pyo3(signature = (manufacturer_code, unique_number, *, device_function, device_class, device_instance, system_instance, industry_group, arbitrary_address_capable))]
#[allow(clippy::too_many_arguments)] // the NAME's fields
fn iso_name(
    manufacturer_code: u16,
    unique_number: u32,
    device_function: u8,
    device_class: u8,
    device_instance: u8,
    system_instance: u8,
    industry_group: u8,
    arbitrary_address_capable: bool,
) -> u64 {
    Name::new(manufacturer_code, unique_number)
        .device_function(device_function)
        .device_class(device_class)
        .device_instance(device_instance)
        .system_instance(system_instance)
        .industry_group(industry_group)
        .arbitrary_address_capable(arbitrary_address_capable)
        .to_u64()
}

/// The ISO 11783-5 address-claim state machine for one NAME.
///
/// `start` scans the bus; `tick` advances the scan and claim deadlines;
/// `on_address_claim` feeds every PGN 60928 heard. Each returns the frames
/// to send. `state` is `"scanning"`, `"pending"`, `"claimed"`, `"failed"`
/// or `"disabled"`.
#[pyclass(module = "nmea2000._canboat")]
struct AddressClaimer {
    inner: Claimer,
}

#[pymethods]
impl AddressClaimer {
    #[new]
    fn new(name: u64, preferred_address: u8, arbitrary_address_capable: bool) -> Self {
        AddressClaimer {
            inner: Claimer::new(name, preferred_address, arbitrary_address_capable),
        }
    }

    fn start<'py>(&mut self, py: Python<'py>, now_ms: u64) -> Vec<FrameTuple<'py>> {
        frames(py, &self.inner.start(now_ms))
    }

    fn tick<'py>(&mut self, py: Python<'py>, now_ms: u64) -> Vec<FrameTuple<'py>> {
        frames(py, &self.inner.tick(now_ms))
    }

    fn on_address_claim<'py>(
        &mut self,
        py: Python<'py>,
        now_ms: u64,
        src: u8,
        name: u64,
    ) -> Vec<FrameTuple<'py>> {
        frames(py, &self.inner.on_address_claim(now_ms, src, name))
    }

    /// Our claim, to answer an ISO Request for PGN 60928, or `None`.
    fn respond_to_claim_request<'py>(&self, py: Python<'py>) -> Option<FrameTuple<'py>> {
        self.inner.respond_to_claim_request().map(|f| frame(py, &f))
    }

    #[getter]
    fn state(&self) -> &'static str {
        match self.inner.state() {
            ClaimState::Scanning => "scanning",
            ClaimState::Pending => "pending",
            ClaimState::Claimed => "claimed",
            ClaimState::Failed => "failed",
            ClaimState::Disabled => "disabled",
        }
    }

    /// The claimed address, or `None` until one is owned.
    #[getter]
    fn address(&self) -> Option<u8> {
        self.inner.address()
    }

    /// The address application frames may be sent from, or `None`.
    #[getter]
    fn send_address(&self) -> Option<u8> {
        self.inner.send_address()
    }

    /// The running scan or claim deadline (ms), when `is_timing`.
    #[getter]
    fn deadline(&self) -> u64 {
        self.inner.deadline()
    }

    #[getter]
    fn is_timing(&self) -> bool {
        self.inner.is_timing()
    }

    #[getter]
    fn name(&self) -> u64 {
        self.inner.name()
    }
}

/// PGN 126996 Product Information from `src`. `nmea2000_version` is raw
/// thousandths (1300 = "1.300").
#[pyfunction]
#[pyo3(signature = (src, *, nmea2000_version, product_code, model_id, software_version, model_version, model_serial, certification_level, load_equivalency))]
#[allow(clippy::too_many_arguments)] // the PGN's fields
fn product_information_frame<'py>(
    py: Python<'py>,
    src: u8,
    nmea2000_version: i64,
    product_code: i64,
    model_id: &str,
    software_version: &str,
    model_version: &str,
    model_serial: &str,
    certification_level: i64,
    load_equivalency: i64,
) -> PyResult<FrameTuple<'py>> {
    let info = ProductInfo {
        db_version: nmea2000_version,
        product_code,
        model_id,
        software_version,
        model_version,
        model_serial,
        certification_level,
        load_equivalency,
    };
    info.frame(src)
        .map(|f| frame(py, &f))
        .ok_or_else(|| super::EncodeError::new_err("product information does not encode"))
}

/// PGN 126993 Heartbeat from `src`, advertising `interval_ms`; an
/// interval the field cannot carry (over 65.532 s) is an `EncodeError`.
#[pyfunction]
fn heartbeat_frame<'py>(
    py: Python<'py>,
    src: u8,
    sequence: u8,
    interval_ms: u64,
) -> PyResult<FrameTuple<'py>> {
    device::heartbeat_frame(src, sequence, interval_ms)
        .map(|f| frame(py, &f))
        .map_err(|e| super::EncodeError::new_err(e.to_string()))
}

/// PGN 59392 ISO Acknowledgement: `control` 0 = ACK, 1 = NAK, 2 = Access
/// Denied, 3 = Cannot Respond.
#[pyfunction]
fn iso_ack_frame<'py>(py: Python<'py>, src: u8, dst: u8, control: u8, pgn: u32) -> FrameTuple<'py> {
    frame(py, &device::iso_ack_frame(src, dst, control, pgn))
}

/// PGN 126464 Transmit and Receive PGN lists, addressed to `dst`.
#[pyfunction]
fn pgn_list_frames<'py>(
    py: Python<'py>,
    src: u8,
    dst: u8,
    transmit: Vec<u32>,
    receive: Vec<u32>,
) -> Vec<FrameTuple<'py>> {
    frames(py, &device::pgn_list_frames(src, dst, &transmit, &receive))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<AddressClaimer>()?;
    m.add_function(wrap_pyfunction!(iso_name, m)?)?;
    m.add_function(wrap_pyfunction!(product_information_frame, m)?)?;
    m.add_function(wrap_pyfunction!(heartbeat_frame, m)?)?;
    m.add_function(wrap_pyfunction!(iso_ack_frame, m)?)?;
    m.add_function(wrap_pyfunction!(pgn_list_frames, m)?)?;
    Ok(())
}
