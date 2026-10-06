//! Decoding straight into nmea2000's `NMEA2000Message` / `NMEA2000Field`.
//!
//! `nmea2000.backend` describes each PGN definition once (a "template":
//! field ids, units, the Python enum members, and how each field's value is
//! presented); after that every message is decoded and built here, without
//! running Python per field. The presentation rules (`Mode`) are documented
//! next to `_MODES` in `nmea2000/backend.py`.

use std::collections::HashMap;

use canboat::schema::{FieldInfo as RsFieldInfo, FieldType, PgnInfo as RsPgnInfo};
use canboat::{
    Database as RsDatabase, DecodedField as RsDecodedField, EncodeValue, FieldId, FieldValue,
    Frame as RsFrame, Units,
};
use pyo3::IntoPyObjectExt;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use super::{DecodeError, UNIX_EPOCH_ORDINAL, bytes_from, encode_value, field_value};

/// How a field's decoded value is presented; see `_MODES` in backend.py.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    Number,
    Lookup,
    Reserved,
    BitLookup,
    Time,
    Date,
    StringFix,
    String,
    Decimal,
    DynamicValue,
    Other,
}

impl Mode {
    fn from_code(code: u8) -> PyResult<Self> {
        Ok(match code {
            0 => Mode::Number,
            1 => Mode::Lookup,
            2 => Mode::Reserved,
            3 => Mode::BitLookup,
            4 => Mode::Time,
            5 => Mode::Date,
            6 => Mode::StringFix,
            7 => Mode::String,
            8 => Mode::Decimal,
            9 => Mode::DynamicValue,
            10 => Mode::Other,
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "unknown field mode",
                ));
            }
        })
    }
}

struct FieldTemplate {
    id: Py<PyString>,
    name: Py<PyAny>,
    description: Py<PyAny>,
    unit: Py<PyAny>,
    quantity: Py<PyAny>,
    ftype: Py<PyAny>,
    primary_key: Py<PyAny>,
    mode: Mode,
    /// canboat.json's (resolution, offset) when its unit is not SI.
    native: Option<(f64, f64)>,
    /// Whole numbers print as int (an integral resolution and no offset).
    integral: bool,
}

struct PgnTemplate {
    fields: Vec<FieldTemplate>,
    /// Each repeating set: (first field, field count, count field).
    sets: Vec<(usize, usize, Option<usize>)>,
    ttl: Py<PyAny>,
    list_ids: [Py<PyString>; 2],
    variable_type: Py<PyAny>,
}

static TIME_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();
static DATE_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();
static TIMEDELTA_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

/// Decodes PGN payloads into nmea2000 message objects, and encodes them back.
///
/// `units` picks the database: `"native"` and `"si"` decode against
/// canboat's SI tables (`"native"` templates carry the rescaling to
/// canboat.json's units), `"metric"` against its metric ones.
/// `template_for(pgn_id)` is called once per PGN definition and returns
/// `(ttl, variable_type, fields)`, `fields` holding one
/// `(id, name, description, unit, quantity, type, part_of_primary_key,
/// mode, native_resolution, native_offset, integral)` per canboat field.
#[pyclass(module = "nmea2000._canboat")]
pub struct MessageCodec {
    db: &'static RsDatabase,
    template_for: Py<PyAny>,
    field_type: Py<PyAny>,
    message_type: Py<PyAny>,
    templates: HashMap<usize, PgnTemplate>,
}

fn template(
    py: Python<'_>,
    info: &'static RsPgnInfo,
    spec: &Bound<'_, PyAny>,
) -> PyResult<PgnTemplate> {
    let (ttl, variable_type, rows): (Py<PyAny>, Py<PyAny>, Bound<'_, PyList>) = spec.extract()?;
    let mut fields = Vec::with_capacity(rows.len());
    for row in rows.iter() {
        let row = row.cast_into::<PyTuple>()?;
        let native_resolution: Option<f64> = row.get_item(8)?.extract()?;
        let native_offset: f64 = row.get_item(9)?.extract()?;
        fields.push(FieldTemplate {
            id: row.get_item(0)?.cast_into::<PyString>()?.unbind(),
            name: row.get_item(1)?.unbind(),
            description: row.get_item(2)?.unbind(),
            unit: row.get_item(3)?.unbind(),
            quantity: row.get_item(4)?.unbind(),
            ftype: row.get_item(5)?.unbind(),
            primary_key: row.get_item(6)?.unbind(),
            mode: Mode::from_code(row.get_item(7)?.extract()?)?,
            native: native_resolution.map(|r| (r, native_offset)),
            integral: row.get_item(10)?.extract()?,
        });
    }
    let sets = [
        (
            info.repeating_field_set1_start_field,
            info.repeating_field_set1_size,
            info.repeating_field_set1_count_field,
        ),
        (
            info.repeating_field_set2_start_field,
            info.repeating_field_set2_size,
            info.repeating_field_set2_count_field,
        ),
    ]
    .into_iter()
    .filter_map(|(start, size, count)| {
        Some((
            start? as usize - 1,
            size? as usize,
            count.map(|c| c as usize - 1),
        ))
    })
    .collect();
    Ok(PgnTemplate {
        fields,
        sets,
        ttl,
        list_ids: [
            PyString::intern(py, "##list##").unbind(),
            PyString::intern(py, "##list2##").unbind(),
        ],
        variable_type,
    })
}

/// The field's bits from the payload, LSB-first; None unless all present.
fn wire_bits(data: &[u8], f: &RsDecodedField) -> Option<(u64, Vec<u8>)> {
    let (start, len) = (f.bit_offset? as usize, f.bit_length? as usize);
    if len == 0 || start + len > data.len() * 8 {
        return None;
    }
    let mut out = vec![0u8; len.div_ceil(8)];
    let mut int = 0u64;
    for i in 0..len {
        let bit = start + i;
        if data[bit / 8] >> (bit % 8) & 1 == 1 {
            out[i / 8] |= 1 << (i % 8);
            if i < 64 {
                int |= 1 << i;
            }
        }
    }
    Some((int, out))
}

fn wire_bytes(py: Python<'_>, data: &[u8], f: &RsDecodedField) -> Py<PyAny> {
    match wire_bits(data, f) {
        Some((_, bytes)) => PyBytes::new(py, &bytes).into_any().unbind(),
        None => py.None(),
    }
}

fn is_absent(v: &FieldValue) -> bool {
    matches!(
        v,
        FieldValue::NotAvailable
            | FieldValue::OutOfRange { .. }
            | FieldValue::ReservedValue { .. }
            | FieldValue::Unsupported { .. }
    )
}

fn number(py: Python<'_>, v: f64, integral: bool) -> PyResult<Py<PyAny>> {
    if integral && v.fract() == 0.0 && v.abs() < 9.0e15 {
        (v as i64).into_py_any(py)
    } else {
        v.into_py_any(py)
    }
}

impl MessageCodec {
    fn template_index(&mut self, py: Python<'_>, info: &'static RsPgnInfo) -> PyResult<usize> {
        let key = info as *const RsPgnInfo as usize;
        if !self.templates.contains_key(&key) {
            let spec = self.template_for.bind(py).call1((info.id,))?;
            let t = template(py, info, &spec)?;
            self.templates.insert(key, t);
        }
        Ok(key)
    }

    /// `(value, raw_value)` the way nmea2000 reports this field.
    fn present(
        &self,
        py: Python<'_>,
        t: &FieldTemplate,
        f: &RsDecodedField,
        data: &[u8],
    ) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        let none = || py.None();
        let v = &f.value;
        let absent = is_absent(v);
        Ok(match t.mode {
            Mode::Number => {
                let value = match (t.native, v) {
                    (Some((res, off)), FieldValue::Number(n)) => {
                        // raw is rebuilt the way the binding's `raw` is
                        let info = f.info;
                        let si_offset = info.offset.unwrap_or(0) as f64 + info.unit_offset;
                        match info.resolution {
                            Some(r) if r != 0.0 => {
                                let raw = ((n - si_offset) / r).round();
                                Some(number(py, raw * res + off, t.integral)?)
                            }
                            _ => None,
                        }
                    }
                    (Some((res, off)), FieldValue::Integer(n)) => {
                        Some(number(py, *n as f64 * res + off, t.integral)?)
                    }
                    (Some(_), _) => None,
                    (None, FieldValue::Number(n) | FieldValue::Float(n)) => {
                        Some(number(py, *n, t.integral)?)
                    }
                    (None, FieldValue::Time { seconds, .. }) => {
                        Some(number(py, *seconds, t.integral)?)
                    }
                    (None, FieldValue::Integer(n)) => Some(n.into_py_any(py)?),
                    (None, FieldValue::Mmsi(n)) => Some(n.into_py_any(py)?),
                    (None, FieldValue::Pgn { value, .. }) => Some(value.into_py_any(py)?),
                    _ => None,
                };
                match value {
                    Some(value) => (value.clone_ref(py), value),
                    None => (none(), none()),
                }
            }
            Mode::Lookup => {
                let (name, raw) = match v {
                    FieldValue::Lookup { value, name } => (*name, Some(*value)),
                    FieldValue::Integer(n) => (None, Some(*n as u64)),
                    FieldValue::OutOfRange { value } | FieldValue::ReservedValue { value } => {
                        (None, Some(*value))
                    }
                    FieldValue::NotAvailable | FieldValue::Unsupported { .. } => {
                        (None, wire_bits(data, f).map(|(int, _)| int))
                    }
                    _ => (None, None),
                };
                let label = name.or_else(|| {
                    let table = self.db.lookup(f.info.lookup_enumeration?)?;
                    Some(table.get(raw?)?.name)
                });
                (
                    match label {
                        Some(l) => PyString::intern(py, l).into_any().unbind(),
                        None => none(),
                    },
                    match raw {
                        Some(r) => r.into_py_any(py)?,
                        None => none(),
                    },
                )
            }
            Mode::Reserved => {
                if absent {
                    (none(), none())
                } else {
                    let (value, raw) = field_value(py, f)?;
                    (value, raw)
                }
            }
            Mode::BitLookup => match v {
                FieldValue::BitField { value, bits } => {
                    let labels: Vec<&str> = bits.iter().filter_map(|(_, name)| *name).collect();
                    (labels.join(", ").into_py_any(py)?, value.into_py_any(py)?)
                }
                _ => (none(), none()),
            },
            Mode::Time => {
                let seconds = match v {
                    FieldValue::Time { seconds, .. } | FieldValue::Number(seconds) => {
                        Some(*seconds)
                    }
                    FieldValue::Integer(n) => Some(*n as f64),
                    _ => None,
                };
                match seconds {
                    Some(s) => {
                        // nmea2000.utils.decode_time: whole seconds, midnight if out of a day
                        let whole = s.trunc() as i64;
                        let (h, m, sec) = if (0..86_400).contains(&whole) {
                            (whole / 3600, whole % 3600 / 60, whole % 60)
                        } else {
                            (0, 0, 0)
                        };
                        let time = TIME_TYPE
                            .import(py, "datetime", "time")?
                            .call1((h, m, sec))?;
                        (time.unbind(), s.into_py_any(py)?)
                    }
                    None => (none(), none()),
                }
            }
            Mode::Date => {
                if absent {
                    (none(), none())
                } else {
                    let (value, raw) = field_value(py, f)?;
                    (value, raw)
                }
            }
            Mode::StringFix | Mode::String => match v {
                FieldValue::String(s) => {
                    let text = s.into_py_any(py)?;
                    let raw = if t.mode == Mode::StringFix {
                        match wire_bits(data, f) {
                            Some((_, bytes)) => PyBytes::new(py, &bytes).into_any().unbind(),
                            None => PyBytes::new(py, s.as_bytes()).into_any().unbind(),
                        }
                    } else {
                        text.clone_ref(py)
                    };
                    (text, raw)
                }
                // nothing to show, but keep the field's bytes so it re-encodes as it was
                _ if t.mode == Mode::StringFix => (none(), wire_bytes(py, data, f)),
                _ => (none(), none()),
            },
            Mode::Decimal => match v {
                FieldValue::Decimal(s) if !s.is_empty() => {
                    let digits = py
                        .get_type::<pyo3::types::PyInt>()
                        .call1((s.as_str(),))?
                        .unbind();
                    (digits.clone_ref(py), digits)
                }
                _ => (none(), none()),
            },
            Mode::DynamicValue => {
                if absent {
                    (none(), wire_bytes(py, data, f))
                } else {
                    let bytes = match v {
                        FieldValue::Binary(b) => Some(b.clone()),
                        _ => wire_bits(data, f).map(|(_, b)| b),
                    };
                    match bytes {
                        Some(b) => {
                            let b = PyBytes::new(py, &b).into_any().unbind();
                            (b.clone_ref(py), b)
                        }
                        None => (none(), none()),
                    }
                }
            }
            Mode::Other => {
                // A VARIABLE (group-function) value is typed by the field it
                // refers to; its raw_value is the bytes on the wire.
                let variable = f.info.field_type == Some(FieldType::Variable);
                if absent {
                    (
                        none(),
                        if variable {
                            wire_bytes(py, data, f)
                        } else {
                            none()
                        },
                    )
                } else {
                    let (value, _) = field_value(py, f)?;
                    let bytes = if variable {
                        wire_bytes(py, data, f)
                    } else {
                        py.None()
                    };
                    let raw = if bytes.is_none(py) {
                        value.clone_ref(py)
                    } else {
                        bytes
                    };
                    (value, raw)
                }
            }
        })
    }

    fn new_field<'py>(
        &self,
        py: Python<'py>,
        t: &FieldTemplate,
        value: Py<PyAny>,
        raw: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.field_type.bind(py).call1((
            t.id.clone_ref(py),
            t.name.clone_ref(py),
            t.description.clone_ref(py),
            t.unit.clone_ref(py),
            value,
            raw,
            t.quantity.clone_ref(py),
            t.ftype.clone_ref(py),
            t.primary_key.clone_ref(py),
        ))
    }
}

// ─────────────────────────────── encode ───────────────────────────────

fn encode_error(message: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(format!("Cant encode this message: {message}"))
}

/// A Python int (not a bool).
fn as_int(obj: &Bound<'_, PyAny>) -> Option<i128> {
    if obj.is_instance_of::<PyInt>() && !obj.is_instance_of::<pyo3::types::PyBool>() {
        obj.extract::<i128>().ok()
    } else {
        None
    }
}

/// A Python int or float (not a bool), as f64.
fn as_number(obj: &Bound<'_, PyAny>) -> Option<f64> {
    if as_int(obj).is_some() || obj.is_instance_of::<PyFloat>() {
        obj.extract::<f64>().ok()
    } else {
        None
    }
}

fn bytes_like(obj: &Bound<'_, PyAny>) -> Option<Vec<u8>> {
    if let Ok(b) = obj.cast::<PyBytes>() {
        return Some(b.as_bytes().to_vec());
    }
    if let Ok(b) = obj.cast::<PyByteArray>() {
        return Some(b.to_vec());
    }
    if obj.get_type().name().ok()? == "memoryview" {
        return obj.call_method0("tobytes").ok()?.extract().ok();
    }
    None
}

fn is_instance(
    py: Python<'_>,
    obj: &Bound<'_, PyAny>,
    cell: &PyOnceLock<Py<PyAny>>,
    name: &str,
) -> PyResult<bool> {
    let ty = cell.import(py, "datetime", name)?;
    obj.is_instance(ty)
}

fn seconds_of_day(time: &Bound<'_, PyAny>) -> PyResult<f64> {
    let get = |a: &str| -> PyResult<f64> { time.getattr(a)?.extract() };
    Ok(get("hour")? * 3600.0 + get("minute")? * 60.0 + get("second")? + get("microsecond")? / 1e6)
}

fn wire_raw(raw: i128, info: &RsFieldInfo) -> EncodeValue {
    let bits = info.bit_length.unwrap_or(64).min(64);
    let mask = if bits >= 64 {
        u64::MAX
    } else {
        (1u64 << bits) - 1
    };
    EncodeValue::Raw((raw as u64) & mask)
}

/// The wire integer for a number outside the schema's range: devices do
/// send such values, and nmea2000 has always written them back as they were.
fn out_of_range_raw(value: &EncodeValue, info: &RsFieldInfo) -> Option<EncodeValue> {
    let v = match value {
        EncodeValue::Number(v) => *v,
        EncodeValue::Int(i) => *i as f64,
        _ => return None,
    };
    let resolution = info.resolution.unwrap_or(1.0);
    let offset = info.offset.unwrap_or(0) as f64 + info.unit_offset;
    let raw = ((v - offset) / resolution).round();
    let bits = info.bit_length?.min(64) as i32;
    let (min, max) = if info.signed.unwrap_or(false) && info.offset.unwrap_or(0) == 0 {
        (-(2f64.powi(bits - 1)), 2f64.powi(bits - 1) - 1.0)
    } else {
        (0.0, 2f64.powi(bits) - 1.0)
    };
    if !(min..=max).contains(&raw) {
        return None; // does not fit the field at all
    }
    Some(wire_raw(raw as i128, info))
}

fn is_numeric_type(t: FieldType) -> bool {
    matches!(
        t,
        FieldType::Number
            | FieldType::Mmsi
            | FieldType::Pgn
            | FieldType::Duration
            | FieldType::FieldIndex
            | FieldType::DynamicFieldLength
    )
}

impl MessageCodec {
    /// What to write instead when canboat refuses a field's value: the wire
    /// bits of a number outside the schema's range, or a group-function
    /// value's own bytes when its typed value does not fit.
    fn fallbacks(
        &self,
        field: &Bound<'_, PyAny>,
        info: &RsFieldInfo,
        value: &EncodeValue,
        error: &canboat::EncodeError,
    ) -> PyResult<Vec<EncodeValue>> {
        if info.field_type == Some(FieldType::Variable)
            && let Some(b) = bytes_like(&field.getattr("raw_value")?)
        {
            // as an integer, or as bytes for a BINARY target
            let mut candidates = Vec::new();
            if b.len() <= 8 {
                let mut le = [0u8; 8];
                le[..b.len()].copy_from_slice(&b);
                candidates.push(EncodeValue::Raw(u64::from_le_bytes(le)));
            }
            candidates.push(EncodeValue::Bytes(b));
            candidates.retain(|c| c != value);
            return Ok(candidates);
        }
        Ok(match error {
            canboat::EncodeError::ValueOutOfRange { .. } => {
                out_of_range_raw(value, info).into_iter().collect()
            }
            _ => Vec::new(),
        })
    }

    /// The canboat value for one NMEA2000Field. `raw_value` wins over
    /// `value` where nmea2000's encoder has always preferred it.
    fn encode_field(
        &self,
        py: Python<'_>,
        field: &Bound<'_, PyAny>,
        t: &FieldTemplate,
        info: &RsFieldInfo,
    ) -> PyResult<EncodeValue> {
        let value = field.getattr("value")?;
        let raw = field.getattr("raw_value")?;
        let ftype = info.field_type.unwrap_or(FieldType::Number);
        let name = || t.name.bind(py).to_string();

        if is_numeric_type(ftype) || ftype == FieldType::Time {
            // An int raw_value that agrees with `value` is the wire integer.
            if let Some(r) = as_int(&raw) {
                let resolution = t
                    .native
                    .map(|(res, _)| res)
                    .or(info.resolution)
                    .unwrap_or(1.0);
                let agrees = if ftype == FieldType::Time
                    && is_instance(py, &value, &TIME_TYPE, "time")?
                {
                    true
                } else {
                    as_number(&value).is_some_and(|v| {
                        ((r as f64) * resolution - v).abs() <= (resolution.abs() * 50.0).max(1e-3)
                    })
                };
                if agrees {
                    return Ok(wire_raw(r, info));
                }
            }
        }
        if is_numeric_type(ftype) {
            let source = if as_number(&raw).is_some() {
                &raw
            } else {
                &value
            };
            if source.is_none() {
                return Ok(EncodeValue::NotAvailable);
            }
            let number = if is_instance(py, source, &TIMEDELTA_TYPE, "timedelta")? {
                source.call_method0("total_seconds")?.extract::<f64>()?
            } else if let Some(n) = as_number(source) {
                if let (Some(i), None) = (as_int(source), t.native) {
                    return Ok(EncodeValue::Int(i as i64));
                }
                n
            } else {
                return Err(PyValueError::new_err(format!(
                    "Cant encode this message, '{}' must be a number",
                    name()
                )));
            };
            return Ok(match t.native {
                // the wire integer, exactly as canboat.json's resolution defines it
                Some((res, off)) => EncodeValue::Raw(((number - off) / res).round() as i64 as u64),
                None => EncodeValue::Number(number),
            });
        }
        match ftype {
            FieldType::Lookup | FieldType::IndirectLookup | FieldType::DynamicFieldKey => {
                if let Some(r) = as_int(&raw) {
                    return Ok(EncodeValue::Int(r as i64));
                }
                encode_value(&value, info)
            }
            FieldType::BitLookup => {
                if let Some(r) = as_int(&raw) {
                    return Ok(EncodeValue::Int(r as i64));
                }
                let Ok(labels) = value.cast::<PyString>() else {
                    return encode_value(&value, info);
                };
                let table = info
                    .lookup_bit_enumeration
                    .and_then(|n| self.db.bit_lookup(n));
                let mut bits = 0u64;
                for label in labels
                    .to_str()?
                    .split(',')
                    .map(str::trim)
                    .filter(|l| !l.is_empty())
                {
                    let bit = table
                        .and_then(|t| t.values.iter().find(|v| v.name == label))
                        .ok_or_else(|| {
                            PyValueError::new_err(format!(
                                "Cant encode this message, {label} is missing from {}",
                                name()
                            ))
                        })?;
                    bits |= 1 << bit.bit;
                }
                Ok(EncodeValue::Int(bits as i64))
            }
            FieldType::Time => {
                if let Some(n) = as_number(&raw) {
                    return Ok(EncodeValue::Number(n));
                }
                let time_type = TIME_TYPE.import(py, "datetime", "time")?;
                let value = match value.cast::<PyString>() {
                    Ok(s) => time_type.call_method1("fromisoformat", (s,))?,
                    Err(_) => value,
                };
                if value.is_instance(time_type)? {
                    return Ok(EncodeValue::Number(seconds_of_day(&value)?));
                }
                encode_value(&value, info)
            }
            FieldType::Date => {
                if let Some(r) = as_int(&raw) {
                    return Ok(EncodeValue::Int(r as i64));
                }
                if let Ok(s) = value.cast::<PyString>() {
                    let date = DATE_TYPE
                        .import(py, "datetime", "date")?
                        .call_method1("fromisoformat", (s,))?;
                    let ordinal: i64 = date.call_method0("toordinal")?.extract()?;
                    return Ok(EncodeValue::Int(ordinal - UNIX_EPOCH_ORDINAL));
                }
                encode_value(&value, info)
            }
            FieldType::Reserved | FieldType::Spare => {
                let bits = if as_int(&raw).is_some() { &raw } else { &value };
                if bits.is_none() {
                    return Ok(EncodeValue::NotAvailable);
                }
                match as_int(bits) {
                    Some(b) => Ok(EncodeValue::Raw(b as u64)),
                    None => Err(PyValueError::new_err(format!(
                        "Cant encode this message, '{}' must be an integer",
                        name()
                    ))),
                }
            }
            FieldType::StringFix | FieldType::StringLz | FieldType::StringLau => {
                if let Some(b) = bytes_like(&raw) {
                    let width = info.bit_length.map(|bits| bits as usize / 8);
                    if ftype == FieldType::StringFix && width == Some(b.len()) {
                        // the field's exact bytes, padding included
                        return Ok(EncodeValue::Bytes(b));
                    }
                    if value.is_none() {
                        return Ok(EncodeValue::Text(String::from_utf8_lossy(&b).into_owned()));
                    }
                }
                encode_value(&value, info)
            }
            FieldType::Variable => {
                // Takes the type of the field it refers to; wire bytes (how
                // nmea2000 used to report it) are written verbatim.
                let data = if value.is_none() { &raw } else { &value };
                match bytes_like(data) {
                    Some(b) if b.len() <= 8 => {
                        let mut le = [0u8; 8];
                        le[..b.len()].copy_from_slice(&b);
                        Ok(EncodeValue::Raw(u64::from_le_bytes(le)))
                    }
                    Some(b) => Ok(EncodeValue::Bytes(b)),
                    None => encode_value(data, info),
                }
            }
            FieldType::Binary | FieldType::DynamicFieldValue => match bytes_like(&raw) {
                Some(b) => Ok(EncodeValue::Bytes(b)),
                None => match bytes_like(&value) {
                    Some(b) => Ok(EncodeValue::Bytes(b)),
                    None => encode_value(&value, info),
                },
            },
            FieldType::IsoName => match as_int(&raw) {
                Some(r) => Ok(EncodeValue::Raw(r as u64)),
                None => encode_value(&value, info),
            },
            FieldType::Decimal => {
                let digits = if as_int(&raw).is_some() { &raw } else { &value };
                if digits.is_none() {
                    return Ok(EncodeValue::NotAvailable);
                }
                let digits: i64 = digits.str()?.to_str()?.parse().map_err(|_| {
                    PyValueError::new_err(format!(
                        "Cant encode this message, '{}' must be decimal digits",
                        name()
                    ))
                })?;
                Ok(EncodeValue::Int(digits))
            }
            _ => encode_value(&value, info),
        }
    }

    /// The instances of repeating set `index` (0 or 1): the `##list##`
    /// entries, or a single instance of the set's fields given top-level.
    fn set_entries<'py>(
        &self,
        py: Python<'py>,
        t: &PgnTemplate,
        index: usize,
        by_id: &HashMap<String, Bound<'py, PyAny>>,
        set_ids: &[String],
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let list_id = t.list_ids[index].bind(py).to_str()?.to_owned();
        if let Some(list_field) = by_id.get(&list_id) {
            let list = list_field.getattr("value")?;
            if list.is_none() {
                return Ok(Vec::new());
            }
            let not_dicts =
                || PyValueError::new_err(format!("{list_id} must be a list of dict items"));
            let list = list.cast_into::<PyList>().map_err(|_| not_dicts())?;
            return list
                .iter()
                .map(|e| e.cast_into::<PyDict>().map_err(|_| not_dicts()))
                .collect();
        }
        // Only set fields that hold something: a decoded message whose set
        // had no instances still lists them, empty.
        let entry = PyDict::new(py);
        for id in set_ids {
            if let Some(f) = by_id.get(id)
                && !(f.getattr("value")?.is_none() && f.getattr("raw_value")?.is_none())
            {
                entry.set_item(id, f)?;
            }
        }
        Ok(if entry.is_empty() {
            Vec::new()
        } else {
            vec![entry]
        })
    }
}

#[pymethods]
impl MessageCodec {
    #[new]
    #[pyo3(signature = (template_for, field_type, message_type, units = "native"))]
    fn new(
        template_for: Py<PyAny>,
        field_type: Py<PyAny>,
        message_type: Py<PyAny>,
        units: &str,
    ) -> PyResult<Self> {
        let units = match units {
            "native" | "si" => Units::Si,
            "metric" => Units::Metric,
            other => return Err(PyValueError::new_err(format!("unknown units {other:?}"))),
        };
        Ok(MessageCodec {
            db: RsDatabase::embedded(units),
            template_for,
            field_type,
            message_type,
            templates: HashMap::new(),
        })
    }

    /// Decode one complete PGN payload into an `NMEA2000Message`. Raises
    /// `DecodeError` for an unknown PGN or a payload too short for it.
    #[pyo3(signature = (pgn, data, src = 0, dst = 255, prio = 6))]
    fn decode<'py>(
        &mut self,
        py: Python<'py>,
        pgn: u32,
        data: &Bound<'py, PyAny>,
        src: u8,
        dst: u8,
        prio: u8,
    ) -> PyResult<Bound<'py, PyAny>> {
        let frame = RsFrame::new(None, prio, pgn, src, dst, bytes_from(data)?);
        let info = self
            .db
            .pick_variant(&frame)
            .ok_or_else(|| DecodeError::new_err(format!("unknown PGN {}", frame.pgn)))?;
        let decoded = self
            .db
            .decode(&frame)
            .map_err(|e| DecodeError::new_err(e.to_string()))?;
        let key = self.template_index(py, info)?;
        let t = &self.templates[&key];
        let base = info.fields.as_ptr_range();

        let fields = PyList::empty(py);
        let mut entries: [Vec<Bound<'py, PyDict>>; 2] = [Vec::new(), Vec::new()];
        let mut counts: HashMap<usize, bool> = HashMap::new(); // count field -> nonzero
        for f in &decoded.fields {
            let ptr: *const canboat::schema::FieldInfo = f.info;
            if !base.contains(&ptr) {
                continue;
            }
            // SAFETY: `ptr` points into `info.fields`, checked just above.
            let index = unsafe { ptr.offset_from(base.start) } as usize;
            let ft = &t.fields[index];
            let (value, raw) = self.present(py, ft, f, &frame.data)?;
            if f.repeat_set == 0 {
                if t.sets.iter().any(|&(_, _, c)| c == Some(index)) {
                    counts.insert(index, value.bind(py).is_truthy()?);
                }
                fields.append(self.new_field(py, ft, value, raw)?)?;
                continue;
            }
            let set = &mut entries[(f.repeat_set - 1) as usize];
            let id = ft.id.bind(py);
            let needs_new = match set.last() {
                None => true,
                Some(entry) => entry.contains(id)?,
            };
            if needs_new {
                set.push(PyDict::new(py));
            }
            set.last()
                .unwrap()
                .set_item(id, self.new_field(py, ft, value, raw)?)?;
        }

        for (i, &(start, size, count)) in t.sets.iter().enumerate() {
            let instances = std::mem::take(&mut entries[i]);
            let zero_count = count.is_some_and(|c| !counts.get(&c).copied().unwrap_or(false));
            if zero_count || instances.is_empty() {
                // nmea2000 has always reported such a set's fields top-level,
                // decoded from whatever bits follow (or empty).
                let first = instances.first();
                for ft in &t.fields[start..start + size] {
                    let existing = match first {
                        Some(entry) => entry.get_item(ft.id.bind(py))?,
                        None => None,
                    };
                    match existing {
                        Some(field) => fields.append(field)?,
                        None => fields.append(self.new_field(py, ft, py.None(), py.None())?)?,
                    }
                }
            } else {
                let list = PyList::new(py, instances)?;
                fields.append(self.field_type.bind(py).call1((
                    t.list_ids[i].clone_ref(py),
                    "List",
                    py.None(),
                    py.None(),
                    list,
                    py.None(),
                    py.None(),
                    t.variable_type.clone_ref(py),
                    false,
                ))?)?;
            }
        }

        let kwargs = PyDict::new(py);
        kwargs.set_item("PGN", pgn)?;
        kwargs.set_item("id", info.id)?;
        kwargs.set_item("description", info.description)?;
        kwargs.set_item("ttl", t.ttl.clone_ref(py))?;
        kwargs.set_item("fields", fields)?;
        self.message_type.bind(py).call((), Some(&kwargs))
    }

    /// Encode an `NMEA2000Message` into its PGN payload (wire order, not
    /// fragmented). Raises ValueError when it cannot be encoded.
    fn encode<'py>(
        &mut self,
        py: Python<'py>,
        message: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let pgn: u32 = message.getattr("PGN")?.extract()?;
        let id: String = message.getattr("id")?.extract().unwrap_or_default();
        let mut variants = self.db.pgn_variants(pgn);
        let first = variants.next();
        let info = match (first, variants.next()) {
            (Some(only), None) if only.id == id || id.is_empty() => only,
            // several variants, or a catch-all definition (the proprietary
            // ranges) that nmea2000 names by its id
            _ => self
                .db
                .pgn_variants(pgn)
                .find(|v| v.id == id)
                .or_else(|| self.db.pgns().find(|v| v.id == id))
                .or(first.filter(|_| self.db.pgn_variants(pgn).count() == 1))
                .ok_or_else(|| {
                    PyValueError::new_err(format!("No encoding function found for PGN: {pgn}"))
                })?,
        };
        let key = self.template_index(py, info)?;
        let t = &self.templates[&key];

        let mut by_id: HashMap<String, Bound<'py, PyAny>> = HashMap::new();
        for field in message.getattr("fields")?.try_iter()? {
            let field = field?;
            by_id.insert(field.getattr("id")?.extract()?, field);
        }

        let src: u8 = message.getattr("source")?.extract()?;
        let dst: u8 = message.getattr("destination")?.extract()?;
        let prio: u8 = message.getattr("priority")?.extract()?;
        let mut builder = self
            .db
            .encode_for(info)
            .source(src)
            .destination(dst)
            .priority(prio);
        let in_set = |i: usize| {
            t.sets
                .iter()
                .any(|&(start, size, _)| (start..start + size).contains(&i))
        };
        for (i, (ft, field_info)) in t.fields.iter().zip(info.fields).enumerate() {
            if in_set(i) {
                continue;
            }
            if let Some(field) = by_id.get(ft.id.bind(py).to_str()?) {
                let value = self.encode_field(py, field, ft, field_info)?;
                let id = FieldId {
                    pgn: info,
                    field: field_info,
                };
                if let Err(error) = builder.push(id, value.clone()) {
                    let pushed = self
                        .fallbacks(field, field_info, &value, &error)?
                        .into_iter()
                        .any(|candidate| builder.push(id, candidate).is_ok());
                    if !pushed {
                        return Err(encode_error(error));
                    }
                }
            }
        }
        for (index, &(start, size, _)) in t.sets.iter().enumerate() {
            let set = index + 1;
            let set_ids: Vec<String> = t.fields[start..start + size]
                .iter()
                .map(|ft| ft.id.bind(py).to_string())
                .collect();
            for entry in self.set_entries(py, t, index, &by_id, &set_ids)? {
                let instance = builder.add_set_instance(set).map_err(encode_error)?;
                for (offset, (ft, id)) in t.fields[start..start + size]
                    .iter()
                    .zip(&set_ids)
                    .enumerate()
                {
                    let field_info = &info.fields[start + offset];
                    // a field the decoder had nothing for stays not available
                    let Some(field) = entry.get_item(id)? else {
                        continue;
                    };
                    if !field.is_instance(self.field_type.bind(py))? {
                        return Err(PyValueError::new_err(format!(
                            "Repeating field '{id}' must be an NMEA2000Field, got {}",
                            field.get_type().name()?
                        )));
                    }
                    let value = self.encode_field(py, &field, ft, field_info)?;
                    let pushed = builder.push_in_set(set, instance, field_info.id, value.clone());
                    if let Err(error) = pushed {
                        let pushed = self
                            .fallbacks(&field, field_info, &value, &error)?
                            .into_iter()
                            .any(|candidate| {
                                builder
                                    .push_in_set(set, instance, field_info.id, candidate)
                                    .is_ok()
                            });
                        if !pushed {
                            return Err(encode_error(error));
                        }
                    }
                }
            }
        }
        let frame = builder.build().map_err(encode_error)?;
        Ok(PyBytes::new(py, &frame.data))
    }
}
