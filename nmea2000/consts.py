from typing import List
from enum import Enum, auto

class PhysicalQuantities(Enum):
    ELECTRICAL_CURRENT = auto(), # Ampere (A)
    ELECTRICAL_CHARGE = auto(), # Coulomb (C)
    ELECTRICAL_ENERGY = auto(), # Kilo Watt Hour (kWh)
    ELECTRICAL_POWER = auto(), # Watt (W)
    ELECTRICAL_APPARENT_POWER = auto(), # Volt Ampere (VA)
    ELECTRICAL_REACTIVE_POWER = auto(), # Volt Ampere Reactive (VAR)
    POTENTIAL_DIFFERENCE = auto(), # Volt (V)
    POWER_FACTOR = auto(), # Cos(Phi) (Cos Phi)
    LENGTH = auto(), # Meter (m)
    DISTANCE = auto(), # meter (m)
    SPEED = auto(), # meter per second (m/s)
    ANGLE = auto(), # radian (rad)
    ANGULAR_VELOCITY = auto(), # radians per second (rad/s)
    VOLUME = auto(), # liter (L)
    VOLUMETRIC_FLOW = auto(), # liter per hour (L/h)
    MAGNETIC_FIELD = auto(), # Tesla (T)
    FREQUENCY = auto(), # Hertz (Hz)
    DATE = auto(), # days (d)
    TIME = auto(), # Second (s)
    DURATION = auto(), # Second (s)
    GEOGRAPHICAL_LATITUDE = auto(), # degree (deg)
    GEOGRAPHICAL_LONGITUDE = auto(), # degree (deg)
    TEMPERATURE = auto(), # Kelvin (K)
    PRESSURE = auto(), # Pascal (Pa)
    PRESSURE_RATE = auto(), # Pascal per hour (Pa/hr)
    CONCENTRATION = auto(), # parts per million (ppm)
    SIGNAL_STRENGTH = auto(), # decibel (dB)
    SIGNAL_TO_NOISE_RATIO = auto(), # decibel (dB)

class FieldTypes(Enum):
    NUMBER = auto(), # Number (Binary numbers are little endian. Number fields that are at least two bits in length use the highest positive value to represent unknown. Number fields with at least 7 as maximum (3 bits unsigned, 4 bits signed) use the highest value minus one as an error indicator. This is likely also true for numbers where 3 is the maximum value, but there are few fields that have this length -- certainly as a number, there are a lot of lookup fields of two bits length.  For signed numbers the maximum values are the maximum positive value and that minus 1, not the all-ones bit encoding which is the maximum negative value.)
    FLOAT = auto(), # 32 bit IEEE-754 floating point number ()
    DECIMAL = auto(), # A unsigned numeric value represented with 2 decimal digits per byte (Each byte represent 2 digits, so 1234 is represented by 2 bytes containing 0x12 and 0x34. A number with an odd number of digits will have 0 as the first digit in the first byte.)
    LOOKUP = auto(), # Number value where each value encodes for a distinct meaning (Each lookup has a LookupEnumeration defining what the possible values mean)
    INDIRECT_LOOKUP = auto(), # Number value where each value encodes for a distinct meaning but the meaning also depends on the value in another field (Each lookup has a LookupIndirectEnumeration defining what the possible values mean)
    BITLOOKUP = auto(), # Number value where each bit value encodes for a distinct meaning (Each LookupBit has a LookupBitEnumeration defining what the possible values mean. A bitfield can have any combination of bits set.)
    DYNAMIC_FIELD_KEY = auto(), # Number value where each value encodes for a distinct meaning including a fieldtype of the next variable field; generally followed by an optional DYNAMIC_FIELD_LENGTH and a DYNAMIC_FIELD_VALUE field; when there is no DYNAMIC_FIELD_LENGTH field the length is contained in the lookup table (Each lookup has a LookupFieldTypeEnumeration defining what the possible values mean)
    DYNAMIC_FIELD_LENGTH = auto(), # Number value that indicates the length of the following DYNAMIC_FIELD_VALUE field ()
    DYNAMIC_FIELD_VALUE = auto(), # Variable field whose type and length is dynamic (The type definition of the field is defined by an earlier LookupFieldTypeEnumeration field. The length is defined by the preceding length field or the length determined by the lookup value.)
    TIME = auto(), # Time ()
    DURATION = auto(), # Duration ()
    DATE = auto(), # Date (The date, in days since 1 January 1970.)
    PGN = auto(), # Parameter Group Number (A 24 bit number referring to a PGN)
    ISO_NAME = auto(), # ISO NAME field (A 64 bit field containing the ISO name, e.g. all fields produced by PGN 60928. Use the definition of PGN 60928 to explain the subfields.)
    STRING_FIX = auto(), # A fixed length string containing single byte codepoints. (The length of the string is determined by the PGN field definition. Trailing bytes have been observed as '@', ' ', 0x0 or 0xff.)
    STRING_LZ = auto(), # A varying length string containing single byte codepoints encoded with a length byte and terminating zero. (The length of the string is determined by a starting length byte. It also contains a terminating zero byte. The length byte includes neither the zero byte or itself. The character encoding is UTF-8.)
    STRING_LAU = auto(), # A varying length string containing double or single byte codepoints encoded with a length byte and terminating zero. (The length of the string is determined by a starting length byte. This count includes the length and type bytes, so any empty string contains count 2. The 2nd byte contains 0 for UNICODE or 1 for ASCII.)
    BINARY = auto(), # Binary field (Unspecified content consisting of any number of bits.)
    RESERVED = auto(), # Reserved field (All reserved bits shall be 1)
    SPARE = auto(), # Spare field (All spare bits shall be 0)
    MMSI = auto(), # MMSI (The MMSI is encoded as a 32 bit number, but is always printed as a 9 digit number and should be considered as a string. The first three or four digits are special, see the USCG link for a detailed explanation.)
    VARIABLE = auto(), # Variable (The definition of the field is that of the reference PGN and reference field, this is totally variable.)
    FIELD_INDEX = auto(), # Field Index (Index of the specified field in the PGN referenced.)


ManufacturerCodes: List[str] = [
    "ARKS Enterprises, Inc.",
    "FW Murphy/Enovation Controls",
    "Twin Disc",
    "Kohler Power Systems",
    "Hemisphere GPS Inc",
    "BEP Marine",
    "Airmar",
    "Maretron",
    "Lowrance",
    "Mercury Marine",
    "Nautibus Electronic GmbH",
    "Blue Water Data",
    "Westerbeke",
    "ISSPRO Inc",
    "Offshore Systems (UK) Ltd.",
    "Evinrude/BRP",
    "CPAC Systems AB",
    "Xantrex Technology Inc.",
    "Marlin Technologies, Inc.",
    "Yanmar Marine",
    "Volvo Penta",
    "Honda Marine",
    "Carling Technologies Inc. (Moritz Aerospace)",
    "Beede Instruments",
    "Floscan Instrument Co. Inc.",
    "Nobletec",
    "Mystic Valley Communications",
    "Actia",
    "Honda Marine",
    "Disenos Y Technologia",
    "Digital Switching Systems",
    "Xintex/Atena",
    "EMMI NETWORK S.L.",
    "Honda Marine",
    "ZF",
    "Garmin",
    "Yacht Monitoring Solutions",
    "Sailormade Marine Telemetry/Tetra Technology LTD",
    "Eride",
    "Honda Marine",
    "Honda Motor Company LTD",
    "Groco",
    "Actisense",
    "Amphenol LTW Technology",
    "Navico",
    "Hamilton Jet",
    "Sea Recovery",
    "Coelmo SRL Italy",
    "BEP Marine",
    "Empir Bus",
    "NovAtel",
    "Sleipner Motor AS",
    "MBW Technologies",
    "Fischer Panda",
    "ICOM",
    "Qwerty",
    "Dief",
    "Boening Automationstechnologie GmbH & Co. KG",
    "Korean Maritime University",
    "Thrane and Thrane",
    "Mastervolt",
    "Fischer Panda Generators",
    "Victron Energy",
    "Rolls Royce Marine",
    "Electronic Design",
    "Northern Lights",
    "Glendinning",
    "B & G",
    "Rose Point Navigation Systems",
    "Johnson Outdoors Marine Electronics Inc Geonav",
    "Capi 2",
    "Beyond Measure",
    "Livorsi Marine",
    "ComNav",
    "Chetco",
    "Fusion Electronics",
    "Standard Horizon",
    "True Heading AB",
    "Egersund Marine Electronics AS",
    "em-trak Marine Electronics",
    "Tohatsu Co, JP",
    "Digital Yacht",
    "Comar Systems Limited",
    "Cummins",
    "VDO (aka Continental-Corporation)",
    "Parker Hannifin aka Village Marine Tech",
    "Alltek Marine Electronics Corp",
    "SAN GIORGIO S.E.I.N",
    "Veethree Electronics & Marine",
    "Humminbird Marine Electronics",
    "SI-TEX Marine Electronics",
    "Sea Cross Marine AB",
    "GME aka Standard Communications Pty LTD",
    "Humminbird Marine Electronics",
    "Ocean Sat BV",
    "Chetco Digitial Instruments",
    "Watcheye",
    "Lcj Capteurs",
    "Attwood Marine",
    "Naviop S.R.L.",
    "Vesper Marine Ltd",
    "Marinesoft Co. LTD",
    "NoLand Engineering",
    "Transas USA",
    "National Instruments Korea",
    "National Marine Electronics Association",
    "Onwa Marine",
    "Webasto",
    "Marinecraft (South Korea)",
    "McMurdo Group aka Orolia LTD",
    "Advansea",
    "KVH",
    "San Jose Technology",
    "Yacht Control",
    "Suzuki Motor Corporation",
    "US Coast Guard",
    "Ship Module aka Customware",
    "Aquatic AV",
    "Aventics GmbH",
    "Intellian",
    "SamwonIT",
    "Arlt Tecnologies",
    "Bavaria Yacts",
    "Diverse Yacht Services",
    "Wema U.S.A dba KUS",
    "Garmin",
    "Shenzhen Jiuzhou Himunication",
    "Rockford Corp",
    "Harman International",
    "JL Audio",
    "Lars Thrane",
    "Autonnic",
    "Yacht Devices",
    "REAP Systems",
    "Au Electronics Group",
    "LxNav",
    "Littelfuse, Inc (formerly Carling Technologies)",
    "DaeMyung",
    "Woosung",
    "ISOTTA IFRA srl",
    "Clarion US",
    "HMI Systems",
    "Ocean Signal",
    "Seekeeper",
    "Poly Planar",
    "Fischer Panda DE",
    "Broyda Industries",
    "Canadian Automotive",
    "Tides Marine",
    "Lumishore",
    "Still Water Designs and Audio",
    "BJ Technologies (Beneteau)",
    "Gill Sensors",
    "Blue Water Desalination",
    "FLIR",
    "Undheim Systems",
    "Lewmar Inc",
    "TeamSurv",
    "Fell Marine",
    "Oceanvolt",
    "Prospec",
    "Data Panel Corp",
    "L3 Technologies",
    "Rhodan Marine Systems",
    "Nexfour Solutions",
    "ASA Electronics",
    "Marines Co (South Korea)",
    "Nautic-on",
    "Sentinel",
    "JL Marine ystems",
    "Ecotronix",
    "Zontisa Marine",
    "EXOR International",
    "Timbolier Industries",
    "TJC Micro",
    "Cox Powertrain",
    "Blue Seas",
    "Kobelt Manufacturing Co. Ltd",
    "Blue Ocean IOT",
    "Xenta Systems",
    "Ultraflex SpA",
    "Lintest SmartBoat",
    "Soundmax",
    "Team Italia Marine (Onyx Marine Automation s.r.l)",
    "Entratech",
    "ITC Inc.",
    "The Marine Guardian LLC",
    "Sonic Corporation",
    "ProNav",
    "Vetus Maxwell INC.",
    "Lithium Pros",
    "Boatrax",
    "Marol Co ltd",
    "CALYPSO Instruments",
    "Spot Zero Water",
    "Lithionics Battery LLC",
    "Quick-teck Electronics Ltd",
    "Uniden America",
    "Nauticoncept",
    "Shadow-Caster LED lighting LLC",
    "Wet Sounds, LLC",
    "E-T-A Circuit Breakers",
    "Scheiber",
    "Smart Yachts International Limited",
    "Dockmate",
    "Bobs Machine",
    "L3Harris ASV",
    "Balmar LLC",
    "Elettromedia spa",
    "Electromaax",
    "Across Oceans Systems Ltd.",
    "Kiwi Yachting",
    "BSB Artificial Intelligence GmbH",
    "Orca Technologoes AS",
    "TBS Electronics BV",
    "Technoton Electroics",
    "MG Energy Systems B.V.",
    "Sea Macine Robotics Inc.",
    "Vista Manufacturing",
    "Zipwake",
    "Sailmon BV",
    "Airmoniq Pro Kft",
    "Sierra Marine",
    "Xinuo Information Technology (Xiamen)",
    "Septentrio",
    "NKE Marine Elecronics",
    "SuperTrack Aps",
    "Honda Electronics Co., LTD",
    "Raritan Engineering Company, Inc",
    "Integrated Power Solutions AG",
    "Interactive Technologies, Inc.",
    "LTG-Tech",
    "Energy Solutions (UK) LTD.",
    "WATT Fuel Cell Corp",
    "Pro Mainer",
    "Dragonfly Energy",
    "Koden Electronics Co., Ltd",
    "Humphree AB",
    "Hinkley Yachts",
    "Global Marine Management GmbH (GMM)",
    "Triskel Marine Ltd",
    "Warwick Control Technologies",
    "Dolphin Charger",
    "Barnacle Systems Inc",
    "Radian IoT, Inc.",
    "Ocean LED Marine Ltd",
    "BluNav",
    "OVA (Nantong Saiyang Electronics Co., Ltd)",
    "RAD Propulsion",
    "Electric Yacht",
    "Elco Motor Yachts",
    "Tecnoseal Foundry S.r.l",
    "Pro Charging Systems, LLC",
    "EVEX Co., LTD",
    "Gobius Sensor Technology AB",
    "Arco Marine",
    "Lenco Marine Inc.",
    "Naocontrol S.L.",
    "Revatek",
    "Aeolionics",
    "PredictWind Ltd",
    "Egis Mobile Electric",
    "Starboard Yacht Group",
    "Roswell Marine",
    "ePropulsion (Guangdong ePropulsion Technology Ltd.)",
    "Micro-Air LLC",
    "Vital Battery",
    "Ride Controller LLC",
    "Tocaro Blue",
    "Vanquish Yachts",
    "FT Technologies",
    "Alps Alpine Co., Ltd.",
    "E-Force Marine",
    "CMC Marine",
    "Nanjing Sandemarine Information Technology Co., Ltd.",
    "Teleflex Marine (SeaStar Solutions)",
    "Raymarine",
    "Navionics",
    "Japan Radio Co",
    "Northstar Technologies",
    "Furuno",
    "Trimble",
    "Simrad",
    "Litton",
    "Kvasar AB",
    "MMP",
    "Vector Cantech",
    "Yamaha Marine",
    "Faria Instruments",]
