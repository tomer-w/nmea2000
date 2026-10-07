//! canboat's sans-I/O gateway codecs (Actisense NGT-1, Digital Yacht
//! iKonvert, Maretron IPG100/200) for nmea2000's asyncio gateway clients:
//! bytes from the gateway in, bus frames and handshake replies out, with
//! the caller owning the port, the event loop and the clock.

use std::time::{SystemTime, UNIX_EPOCH};

use canboat::Frame as RsFrame;
use canboat::codec::{Codec, Event, PgnLists, ikonvert, maretron, ngt1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList};

use super::{EncodeError, bytes_from};

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// One gateway's protocol state.
///
/// `kind` is `"ngt1"`, `"ikonvert"` or `"maretron"`. `tx_pgns` and
/// `rx_pgns` are the PGNs the application sends and reads: an NGT-1 or
/// iKonvert only transmits PGNs on its transmit list, so once `tx_pgns`
/// names any, every other PGN (apart from network management) is refused.
/// `password` is the Maretron IPG login.
///
/// Events come back as `("frame", (prio, pgn, src, dst, data))` for a
/// complete PGN, `("send", bytes)` for bytes to write to the gateway now,
/// and `("error", message)`.
#[pyclass(module = "nmea2000._canboat")]
pub struct GatewayCodec {
    inner: Box<dyn Codec + Send + Sync>,
}

fn events_to_python<'py>(py: Python<'py>, events: Vec<Event>) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for event in events {
        match event {
            Event::Frame(f) => list.append((
                "frame",
                (f.prio, f.pgn, f.src, f.dst, PyBytes::new(py, &f.data)),
            ))?,
            Event::Send(bytes) => list.append(("send", PyBytes::new(py, &bytes)))?,
            Event::Error(message) => list.append(("error", message))?,
        }
    }
    Ok(list)
}

#[pymethods]
impl GatewayCodec {
    #[new]
    #[pyo3(signature = (kind, *, tx_pgns = Vec::new(), rx_pgns = Vec::new(), password = String::new()))]
    fn new(kind: &str, tx_pgns: Vec<u32>, rx_pgns: Vec<u32>, password: String) -> PyResult<Self> {
        let pgn_lists = PgnLists {
            tx: tx_pgns,
            rx: rx_pgns,
        };
        let inner: Box<dyn Codec + Send + Sync> = match kind {
            "ngt1" => Box::new(ngt1::Ngt1::new(ngt1::Config {
                pgn_lists,
                ..Default::default()
            })),
            "ikonvert" => Box::new(ikonvert::Ikonvert::new(ikonvert::Config {
                pgn_lists,
                ..Default::default()
            })),
            "maretron" => Box::new(maretron::Maretron::new(maretron::Config { password })),
            other => return Err(PyValueError::new_err(format!("unknown gateway {other:?}"))),
        };
        Ok(GatewayCodec { inner })
    }

    /// Bytes to write as soon as the link is up.
    fn open<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.open())
    }

    /// Bytes to write when closing the link on purpose.
    fn close<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.close())
    }

    /// `(interval_seconds, bytes)` to write whenever the link has carried
    /// nothing for that long, or `None`.
    fn keepalive<'py>(&self, py: Python<'py>) -> Option<(f64, Bound<'py, PyBytes>)> {
        self.inner
            .keepalive()
            .map(|(interval, bytes)| (interval.as_secs_f64(), PyBytes::new(py, &bytes)))
    }

    /// Feed bytes read from the gateway; returns the events they complete.
    #[pyo3(signature = (data, now_ms = None))]
    fn receive<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'py, PyAny>,
        now_ms: Option<u64>,
    ) -> PyResult<Bound<'py, PyList>> {
        let mut events = Vec::new();
        self.inner.receive(
            &bytes_from(data)?,
            now_ms.unwrap_or_else(self::now_ms),
            &mut events,
        );
        events_to_python(py, events)
    }

    /// Let the codec's deadlines advance while nothing arrives; call it
    /// every quarter of a second or so.
    #[pyo3(signature = (now_ms = None))]
    fn tick<'py>(&mut self, py: Python<'py>, now_ms: Option<u64>) -> PyResult<Bound<'py, PyList>> {
        let mut events = Vec::new();
        self.inner
            .tick(now_ms.unwrap_or_else(self::now_ms), &mut events);
        events_to_python(py, events)
    }

    /// Encode a complete PGN payload for the gateway. Raises
    /// `EncodeError` when the gateway would not send it.
    #[pyo3(signature = (pgn, data, src = 0, dst = 255, prio = 6))]
    fn send<'py>(
        &mut self,
        py: Python<'py>,
        pgn: u32,
        data: &Bound<'py, PyAny>,
        src: u8,
        dst: u8,
        prio: u8,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let frame = RsFrame::new(None, prio, pgn, src, dst, bytes_from(data)?);
        let bytes = self
            .inner
            .send(&frame)
            .map_err(|refused| EncodeError::new_err(format!("PGN {pgn}: {refused}")))?;
        Ok(PyBytes::new(py, &bytes))
    }
}
