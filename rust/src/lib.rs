//! nmea2000's compiled core: the `canboat` crate exposed to Python as
//! `nmea2000._canboat`.
//!
//! Every decision about bits, scaling, sentinels and lookups is the crate's;
//! this layer converts between Rust and Python values. Decoding builds
//! nmea2000's message objects directly (see `message`); encoding, schema
//! introspection and fast-packet reassembly are exposed for
//! `nmea2000.backend` and `nmea2000.decoder`.

mod device;
mod gateway;
mod message;

use canboat::schema::{
    BusProtocol, FieldInfo as RsFieldInfo, FieldType, PacketType, PgnInfo as RsPgnInfo,
};
use canboat::{
    Database as RsDatabase, DecodedField as RsDecodedField, EncodeValue, FieldId, FieldValue,
    Frame as RsFrame, Reassembled, Reassembler as RsReassembler, Units,
};
use pyo3::IntoPyObjectExt;
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyKeyError, PyTypeError};
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyByteArray, PyBytes, PyDate, PyDict, PyList, PyString};

create_exception!(
    nmea2000._canboat,
    DecodeError,
    PyException,
    "A payload could not be decoded."
);
create_exception!(
    nmea2000._canboat,
    EncodeError,
    PyException,
    "A message could not be encoded."
);
create_exception!(
    nmea2000._canboat,
    ReassemblyError,
    PyException,
    "A fast-packet or ISO-TP frame could not be reassembled."
);

/// `datetime.date(1970, 1, 1).toordinal()`: N2K dates count days from it.
const UNIX_EPOCH_ORDINAL: i64 = 719_163;

// ─────────────────────────────── helpers ───────────────────────────────

fn bytes_from(obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    if let Ok(b) = obj.cast::<PyBytes>() {
        Ok(b.as_bytes().to_vec())
    } else if let Ok(b) = obj.cast::<PyByteArray>() {
        Ok(b.to_vec())
    } else if obj.cast::<PyString>().is_ok() {
        Err(PyTypeError::new_err("expected bytes, not str"))
    } else {
        obj.extract::<Vec<u8>>()
    }
}

fn field_type_name(t: FieldType) -> &'static str {
    // The spelling canboat.json uses for `FieldType`.
    match t {
        FieldType::Number => "NUMBER",
        FieldType::Decimal => "DECIMAL",
        FieldType::Float => "FLOAT",
        FieldType::Binary => "BINARY",
        FieldType::Lookup => "LOOKUP",
        FieldType::BitLookup => "BITLOOKUP",
        FieldType::IndirectLookup => "INDIRECT_LOOKUP",
        FieldType::Date => "DATE",
        FieldType::Time => "TIME",
        FieldType::Duration => "DURATION",
        FieldType::StringFix => "STRING_FIX",
        FieldType::StringLz => "STRING_LZ",
        FieldType::StringLau => "STRING_LAU",
        FieldType::Variable => "VARIABLE",
        FieldType::Mmsi => "MMSI",
        FieldType::Pgn => "PGN",
        FieldType::IsoName => "ISO_NAME",
        FieldType::Reserved => "RESERVED",
        FieldType::Spare => "SPARE",
        FieldType::DynamicFieldKey => "DYNAMIC_FIELD_KEY",
        FieldType::DynamicFieldLength => "DYNAMIC_FIELD_LENGTH",
        FieldType::DynamicFieldValue => "DYNAMIC_FIELD_VALUE",
        FieldType::FieldIndex => "FIELD_INDEX",
        FieldType::Address => "ADDRESS",
    }
}

fn is_lookup(f: &RsFieldInfo) -> bool {
    matches!(
        f.field_type,
        Some(FieldType::Lookup | FieldType::BitLookup | FieldType::IndirectLookup)
    )
}

fn encode_err(e: canboat::EncodeError) -> PyErr {
    EncodeError::new_err(e.to_string())
}

/// Repeating set `set` (1 or 2) of `pgn` as (first field index, field count).
fn set_layout(pgn: &RsPgnInfo, set: usize) -> Option<(usize, usize)> {
    let (start, size) = match set {
        1 => (
            pgn.repeating_field_set1_start_field,
            pgn.repeating_field_set1_size,
        ),
        2 => (
            pgn.repeating_field_set2_start_field,
            pgn.repeating_field_set2_size,
        ),
        _ => (None, None),
    };
    Some((start? as usize - 1, size? as usize))
}

static DATE_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

/// canboat's decoded value as `(value, raw)`: the natural Python value
/// (`float`, `int`, `str`, `bytes`, `datetime.date`, a list of set-bit
/// labels, or `None` when not available) and the wire integer where there is
/// one.
fn field_value(py: Python<'_>, f: &RsDecodedField) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    let info = f.info;
    let none = || py.None();
    let same = |v: Py<PyAny>| (v.clone_ref(py), v);
    Ok(match &f.value {
        FieldValue::Number(v) => {
            // The decoder computes `raw * resolution + offset + unit_offset`;
            // invert it to get the wire integer back.
            let raw = match info.resolution {
                Some(res) if res != 0.0 => {
                    let offset = info.offset.unwrap_or(0) as f64 + info.unit_offset;
                    (((v - offset) / res).round() as i64).into_py_any(py)?
                }
                _ => none(),
            };
            (v.into_py_any(py)?, raw)
        }
        FieldValue::Integer(v) => same(v.into_py_any(py)?),
        FieldValue::Float(v) => (v.into_py_any(py)?, none()),
        FieldValue::Binary(b) => (PyBytes::new(py, b).into_any().unbind(), none()),
        FieldValue::Lookup { value, name } => {
            let shown = match name {
                Some(n) => PyString::intern(py, n).into_any().unbind(),
                None => value.into_py_any(py)?,
            };
            (shown, value.into_py_any(py)?)
        }
        FieldValue::BitField { value, bits } => {
            let labels = PyList::empty(py);
            for (bit, name) in bits {
                match name {
                    Some(n) => labels.append(n)?,
                    None => labels.append(bit)?,
                }
            }
            (labels.into_any().unbind(), value.into_py_any(py)?)
        }
        FieldValue::Decimal(s) | FieldValue::String(s) => (s.into_py_any(py)?, none()),
        FieldValue::Date(days) => {
            let date_type = DATE_TYPE.import(py, "datetime", "date")?;
            let date =
                date_type.call_method1("fromordinal", (UNIX_EPOCH_ORDINAL + *days as i64,))?;
            (date.unbind(), days.into_py_any(py)?)
        }
        FieldValue::Time { raw, seconds } => (seconds.into_py_any(py)?, raw.into_py_any(py)?),
        FieldValue::Mmsi(v) => same(v.into_py_any(py)?),
        FieldValue::Pgn { value, .. } => same(value.into_py_any(py)?),
        FieldValue::IsoName { value, .. }
        | FieldValue::Reserved { value, .. }
        | FieldValue::Spare { value, .. } => same(value.into_py_any(py)?),
        FieldValue::OutOfRange { value } | FieldValue::ReservedValue { value } => {
            (none(), value.into_py_any(py)?)
        }
        FieldValue::NotAvailable | FieldValue::Unsupported { .. } => (none(), none()),
    })
}

// ─────────────────────────────── encode values ───────────────────────────────

/// A field's wire bits, written verbatim by `Database.encode`: no scaling
/// and no range check, so it can deliberately write a sentinel.
#[pyclass(module = "nmea2000._canboat", frozen, eq)]
#[derive(PartialEq)]
struct Raw {
    #[pyo3(get)]
    value: u64,
}

#[pymethods]
impl Raw {
    #[new]
    fn new(value: u64) -> Self {
        Raw { value }
    }

    fn __repr__(&self) -> String {
        format!("Raw({:#x})", self.value)
    }
}

fn encode_value(obj: &Bound<'_, PyAny>, field: &RsFieldInfo) -> PyResult<EncodeValue> {
    if obj.is_none() {
        return Ok(EncodeValue::NotAvailable);
    }
    if let Ok(raw) = obj.cast::<Raw>() {
        return Ok(EncodeValue::Raw(raw.get().value));
    }
    if let Ok(b) = obj.extract::<bool>() {
        return Ok(EncodeValue::Int(b as i64));
    }
    if let Ok(s) = obj.cast::<PyString>() {
        let s = s.to_str()?.to_owned();
        return Ok(if is_lookup(field) {
            EncodeValue::Lookup(s)
        } else {
            EncodeValue::Text(s)
        });
    }
    if obj.cast::<PyBytes>().is_ok() || obj.cast::<PyByteArray>().is_ok() {
        return Ok(EncodeValue::Bytes(bytes_from(obj)?));
    }
    if let Ok(d) = obj.cast::<PyDate>() {
        let ordinal: i64 = d.call_method0("toordinal")?.extract()?;
        return Ok(EncodeValue::Int(ordinal - UNIX_EPOCH_ORDINAL));
    }
    if obj.is_instance_of::<pyo3::types::PyInt>() {
        if let Ok(i) = obj.extract::<i64>() {
            return Ok(EncodeValue::Int(i));
        }
        // Past i64 only an unscaled code (a 64-bit ISO NAME) makes sense.
        return Ok(EncodeValue::Raw(obj.extract::<u64>()?));
    }
    if let Ok(f) = obj.extract::<f64>() {
        return Ok(EncodeValue::Number(f));
    }
    Err(PyTypeError::new_err(format!(
        "cannot encode a {} into field '{}'",
        obj.get_type().name()?,
        field.id
    )))
}

// ─────────────────────────────── schema ───────────────────────────────

/// One field definition of a PGN, from the CANboat database.
#[pyclass(module = "nmea2000._canboat", frozen)]
struct FieldInfo {
    info: &'static RsFieldInfo,
}

#[pymethods]
impl FieldInfo {
    /// camelCase identifier, unique within the PGN (e.g. `"windSpeed"`).
    #[getter]
    fn id(&self) -> &'static str {
        self.info.id
    }
    /// Human-readable name (e.g. `"Wind Speed"`).
    #[getter]
    fn name(&self) -> &'static str {
        self.info.name
    }
    #[getter]
    fn description(&self) -> Option<&'static str> {
        self.info.description
    }
    /// canboat.json `FieldType` spelling (e.g. `"NUMBER"`, `"LOOKUP"`).
    #[getter]
    fn field_type(&self) -> Option<&'static str> {
        self.info.field_type.map(field_type_name)
    }
    #[getter]
    fn unit(&self) -> Option<&'static str> {
        self.info.unit
    }
    #[getter]
    fn physical_quantity(&self) -> Option<&'static str> {
        self.info.physical_quantity
    }
    #[getter]
    fn resolution(&self) -> Option<f64> {
        self.info.resolution
    }
    #[getter]
    fn offset(&self) -> Option<i64> {
        self.info.offset
    }
    #[getter]
    fn bit_offset(&self) -> Option<u32> {
        self.info.bit_offset
    }
    #[getter]
    fn bit_length(&self) -> Option<u32> {
        self.info.bit_length
    }
    #[getter]
    fn part_of_primary_key(&self) -> bool {
        self.info.part_of_primary_key.unwrap_or(false)
    }
    #[getter]
    fn lookup_bit_enumeration(&self) -> Option<&'static str> {
        self.info.lookup_bit_enumeration
    }

    fn __repr__(&self) -> String {
        format!("FieldInfo(id={:?})", self.info.id)
    }
}

/// One PGN definition (a PGN number may have several, e.g. per manufacturer).
#[pyclass(module = "nmea2000._canboat", frozen)]
struct PgnInfo {
    info: &'static RsPgnInfo,
}

#[pymethods]
impl PgnInfo {
    #[getter]
    fn pgn(&self) -> u32 {
        self.info.pgn
    }
    /// camelCase identifier, unique across the database (e.g. `"windData"`).
    #[getter]
    fn id(&self) -> &'static str {
        self.info.id
    }
    /// `"Single"`, `"Fast"`, `"ISO"` or `"Mixed"`.
    #[getter]
    fn packet_type(&self) -> &'static str {
        match self.info.packet_type {
            PacketType::Single => "Single",
            PacketType::Fast => "Fast",
            PacketType::Iso => "ISO",
            PacketType::Mixed => "Mixed",
        }
    }
    #[getter]
    fn transmission_interval(&self) -> Option<u32> {
        self.info.transmission_interval
    }
    #[getter]
    fn fields(&self) -> Vec<FieldInfo> {
        self.info
            .fields
            .iter()
            .map(|info| FieldInfo { info })
            .collect()
    }
    /// The repeating field sets as `(first field index, field count,
    /// count field index or None)`, 0-based into `fields`; at most two.
    #[getter]
    fn repeating_sets(&self) -> Vec<(usize, usize, Option<usize>)> {
        [
            self.info.repeating_field_set1_count_field,
            self.info.repeating_field_set2_count_field,
        ]
        .into_iter()
        .enumerate()
        .filter_map(|(i, count)| {
            let (start, size) = set_layout(self.info, i + 1)?;
            Some((start, size, count.map(|c| c as usize - 1)))
        })
        .collect()
    }

    fn __repr__(&self) -> String {
        format!("PgnInfo(pgn={}, id={:?})", self.info.pgn, self.info.id)
    }
}

// ─────────────────────────────── database ───────────────────────────────

/// The compiled CANboat PGN database: `units` is `"si"` (the default) or
/// `"metric"` (deg, °C, bar, ...).
#[pyclass(module = "nmea2000._canboat", frozen)]
struct Database {
    db: &'static RsDatabase,
}

/// Items of a `Mapping[str, Any]`.
fn items<'py>(obj: &Bound<'py, PyAny>) -> PyResult<Vec<(String, Bound<'py, PyAny>)>> {
    obj.cast::<PyDict>()?
        .iter()
        .map(|(k, v)| Ok((k.extract()?, v)))
        .collect()
}

#[pymethods]
impl Database {
    #[new]
    #[pyo3(signature = (units = "si"))]
    fn new(units: &str) -> PyResult<Self> {
        let units = match units {
            "si" => Units::Si,
            "metric" => Units::Metric,
            other => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unknown units {other:?}"
                )));
            }
        };
        Ok(Database {
            db: RsDatabase::embedded(units),
        })
    }

    /// The canboat release the database comes from (e.g. `"8.3.0"`).
    #[getter]
    fn version(&self) -> &'static str {
        self.db.version
    }

    /// Every PGN definition, manufacturer variants included.
    fn pgns(&self) -> Vec<PgnInfo> {
        self.db.pgns().map(|info| PgnInfo { info }).collect()
    }

    /// The definitions of PGN number `pgn` (empty when unknown).
    fn pgn_variants(&self, pgn: u32) -> Vec<PgnInfo> {
        self.db
            .pgn_variants(pgn)
            .map(|info| PgnInfo { info })
            .collect()
    }

    /// The definition with id `id` (e.g. `"windData"`).
    fn pgn_info(&self, id: &str) -> PyResult<PgnInfo> {
        self.db
            .pgns()
            .find(|p| p.id == id)
            .map(|info| PgnInfo { info })
            .ok_or_else(|| PyKeyError::new_err(id.to_owned()))
    }

    /// The `LOOKUP` enumeration `name` as `[(value, label), ...]`, in
    /// canboat's order.
    fn lookup(&self, name: &str) -> PyResult<Vec<(u64, &'static str)>> {
        let table = self
            .db
            .lookup(name)
            .ok_or_else(|| PyKeyError::new_err(name.to_owned()))?;
        Ok(table.values.iter().map(|v| (v.value, v.name)).collect())
    }

    /// The `BITLOOKUP` enumeration `name` as `[(bit, label), ...]`.
    fn bit_lookup(&self, name: &str) -> PyResult<Vec<(u8, &'static str)>> {
        let table = self
            .db
            .bit_lookup(name)
            .ok_or_else(|| PyKeyError::new_err(name.to_owned()))?;
        Ok(table.values.iter().map(|v| (v.bit, v.name)).collect())
    }

    /// Encode the PGN definition `pgn_id` (e.g. `"windData"`) into its
    /// payload bytes.
    ///
    /// `fields` maps field ids to values; unset fields take their schema
    /// defaults (normally "not available"). A float or int is a value in the
    /// field's SI unit, a `str` is a lookup label (or text), and `Raw(n)`
    /// writes the wire bits verbatim. `sets` gives the instances of the
    /// repeating field sets: `sets[0]` is a list of mappings for set 1,
    /// `sets[1]` for set 2.
    #[pyo3(signature = (pgn_id, fields, *, src = 0, dst = 255, prio = None, sets = None))]
    #[allow(clippy::too_many_arguments)] // the Python signature
    fn encode<'py>(
        &self,
        py: Python<'py>,
        pgn_id: &str,
        fields: &Bound<'py, PyAny>,
        src: u8,
        dst: u8,
        prio: Option<u8>,
        sets: Option<Vec<Vec<Bound<'py, PyAny>>>>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let mut builder = self
            .db
            .encode(pgn_id)
            .map_err(encode_err)?
            .source(src)
            .destination(dst);
        if let Some(prio) = prio {
            builder = builder.priority(prio);
        }
        let info = builder.pgn_info();
        for (key, value) in items(fields)? {
            let field =
                info.fields.iter().find(|f| f.id == key).ok_or_else(|| {
                    EncodeError::new_err(format!("{} has no field {key:?}", info.id))
                })?;
            let value = encode_value(&value, field)?;
            builder
                .push(FieldId { pgn: info, field }, value)
                .map_err(encode_err)?;
        }
        for (i, instances) in sets.unwrap_or_default().into_iter().enumerate() {
            let set = i + 1;
            let (start, size) = set_layout(info, set).ok_or_else(|| {
                EncodeError::new_err(format!("{} has no repeating set {set}", info.id))
            })?;
            let set_fields = &info.fields[start..start + size];
            for instance_fields in instances {
                let instance = builder.add_set_instance(set).map_err(encode_err)?;
                for (key, value) in items(&instance_fields)? {
                    let field = set_fields.iter().find(|f| f.id == key).ok_or_else(|| {
                        EncodeError::new_err(format!(
                            "repeating set {set} of {} has no field {key:?}",
                            info.id
                        ))
                    })?;
                    let value = encode_value(&value, field)?;
                    builder
                        .push_in_set(set, instance, field.id, value)
                        .map_err(encode_err)?;
                }
            }
        }
        let frame = builder.build().map_err(encode_err)?;
        Ok(PyBytes::new(py, &frame.data))
    }
}

// ─────────────────────────────── reassembly ───────────────────────────────

/// Joins fast-packet and ISO-TP frames into complete PGNs.
///
/// Feed it every CAN frame in arrival order; `push` returns the complete
/// payload of a single-frame PGN or a finished multi-frame one, and `None`
/// while a message is still incomplete.
#[pyclass(module = "nmea2000._canboat")]
struct Reassembler {
    inner: RsReassembler,
}

#[pymethods]
impl Reassembler {
    #[new]
    fn new() -> Self {
        Reassembler {
            inner: RsReassembler::new(),
        }
    }

    #[pyo3(signature = (pgn, data, src = 0, dst = 255, prio = 6))]
    fn push<'py>(
        &mut self,
        py: Python<'py>,
        pgn: u32,
        data: &Bound<'py, PyAny>,
        src: u8,
        dst: u8,
        prio: u8,
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        let frame = RsFrame::new(None, prio, pgn, src, dst, bytes_from(data)?);
        match self
            .inner
            .push(frame, BusProtocol::Nmea2000.packet_type(pgn))
        {
            Reassembled::Complete(f) | Reassembled::PassThrough(f) => {
                Ok(Some(PyBytes::new(py, &f.data)))
            }
            Reassembled::Partial => Ok(None),
            Reassembled::Error(e) => Err(ReassemblyError::new_err(e.to_string())),
        }
    }
}

// ─────────────────────────────── text formats ───────────────────────────────

/// `(prio, pgn, src, dst, data)`
type ParsedFrame<'py> = (u8, u32, u8, u8, Bound<'py, PyBytes>);

/// Parse one line of a text capture or gateway stream with canboat's parser
/// for `format`: `"plain"` (canboat PLAIN/FAST: one frame, or a coalesced
/// fast-packet when it carries more than 8 bytes), `"actisense_ascii"`,
/// `"ydwg02"`, `"chetco"` (`$PCDIN`), `"ikonvert"` (`!PDGY`), `"candump"`,
/// `"airmar"`, `"garmin_csv"` or `"garmin_csv2"`.
///
/// Returns `(prio, pgn, src, dst, data)`, or `None` for a line that carries
/// no frame (a control sentence, a header). Raises `ValueError` for a line
/// that is not in that format.
#[pyfunction]
fn parse_line<'py>(
    py: Python<'py>,
    format: &str,
    line: &str,
) -> PyResult<Option<ParsedFrame<'py>>> {
    use canboat::codec::line::InputFormat;
    let format = match format {
        "plain" => InputFormat::PlainMixFast,
        "actisense_ascii" => InputFormat::ActisenseAscii,
        "ydwg02" => InputFormat::Ydwg02,
        "chetco" => InputFormat::Chetco,
        "ikonvert" => InputFormat::Ikonvert,
        "candump" => InputFormat::Candump,
        "airmar" => InputFormat::Airmar,
        "garmin_csv" => InputFormat::GarminCsv,
        "garmin_csv2" => InputFormat::GarminCsv2,
        other => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown line format {other:?}"
            )));
        }
    };
    let frame = canboat::codec::line::parse(format, line)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("{e}: {line:?}")))?;
    Ok(frame.map(|f| (f.prio, f.pgn, f.src, f.dst, PyBytes::new(py, &f.data))))
}

// ─────────────────────────────── CAN framing ───────────────────────────────

/// Split a fast-packet payload (at most 223 bytes) into 8-byte CAN frames
/// with sequence counter `seq` (0-7); the last frame is padded with 0xff.
#[pyfunction]
fn fast_packet_fragment<'py>(
    py: Python<'py>,
    seq: u8,
    data: &Bound<'py, PyAny>,
) -> PyResult<Vec<Bound<'py, PyBytes>>> {
    let data = bytes_from(data)?;
    let frames = canboat::codec::fastpacket::fragment(seq, &data).ok_or_else(|| {
        EncodeError::new_err(format!(
            "{} bytes is too long for a fast-packet",
            data.len()
        ))
    })?;
    Ok(frames.iter().map(|f| PyBytes::new(py, f)).collect())
}

/// The 29-bit CAN identifier for `(prio, pgn, src, dst)`.
#[pyfunction]
fn can_id_compose(prio: u8, pgn: u32, src: u8, dst: u8) -> u32 {
    canboat::codec::can_id::compose(prio, pgn, src, dst)
}

/// Split a 29-bit CAN identifier into `(prio, pgn, src, dst)`.
#[pyfunction]
fn can_id_decompose(can_id: u32) -> (u8, u32, u8, u8) {
    canboat::codec::can_id::decompose(can_id)
}

#[pymodule]
fn _canboat(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("DecodeError", py.get_type::<DecodeError>())?;
    m.add("EncodeError", py.get_type::<EncodeError>())?;
    m.add("ReassemblyError", py.get_type::<ReassemblyError>())?;
    m.add_class::<Database>()?;
    m.add_class::<FieldInfo>()?;
    m.add_class::<PgnInfo>()?;
    m.add_class::<Raw>()?;
    m.add_class::<Reassembler>()?;
    m.add_class::<message::MessageCodec>()?;
    m.add_class::<gateway::GatewayCodec>()?;
    device::register(m)?;
    m.add_function(wrap_pyfunction!(fast_packet_fragment, m)?)?;
    m.add_function(wrap_pyfunction!(parse_line, m)?)?;
    m.add_function(wrap_pyfunction!(can_id_compose, m)?)?;
    m.add_function(wrap_pyfunction!(can_id_decompose, m)?)?;
    Ok(())
}
