import sys
import logging
import binascii
from datetime import datetime, timedelta
from typing import Tuple
from .message import NMEA2000Message
from .pgns import *  # noqa: F403
from .consts import PhysicalQuantities
import os
import uuid

logger = logging.getLogger(__name__)

class fast_pgn_metadata():
    def __init__(self) -> None:
        self.frames = {}
        self.payload_length = 0
        self.bytes_stored = 0
        self.sequence_counter = -1

    def __repr__(self):
        return f"<fast_pgn_metadata frames={len(self.frames)} payload_length={self.payload_length} bytes_stored={self.bytes_stored} sequence_counter={self.sequence_counter}>"

class NMEA2000Decoder():
    def __init__(self, exclude_pgns:list[str]=[], include_pgns:list[str]=[], preferred_units:dict[PhysicalQuantities, str]={}, dump_to_folder: str | None = None) -> None:
        self.data = {}
        self.dump_to_folder = dump_to_folder
        if not isinstance(exclude_pgns, list):
            raise ValueError("exclude_pgns must be a list")
        if not isinstance(include_pgns, list):
            raise ValueError("include_pgns must be a list")
        if len(exclude_pgns) > 0 and len(include_pgns) > 0:
            raise ValueError("Only one of exclude_pgns or include_pgns can be used")
        
        self.exclude_pgns = exclude_pgns
        self.include_pgns = include_pgns
        self.preferred_units = {k: v.lower() for k, v in preferred_units.items()}
        

    def _decode_fast_message(self, pgn, priority, src, dest, timestamp, can_data) -> NMEA2000Message | None:
        """Parse a fast packet message and store the data until all frames are received."""
        fast_packet_key = f"{pgn}_{src}_{dest}"
        
        # Check if this PGN already has a storage structure; if not, create one
        if self.data.get(fast_packet_key) is None:
            self.data[fast_packet_key] = fast_pgn_metadata()
            
        fast_pgn = self.data[fast_packet_key]

        # the last byte has the sequence_counter and frame_counter
        last_byte = can_data[-1]
        
        # Extract the sequence counter (high 3 bits) and frame counter (low 5 bits) from the last byte
        sequence_counter = (last_byte >> 5) & 0b111  # Extract high 3 bits
        frame_counter = last_byte & 0b11111  # Extract low 5 bits
        
        total_bytes = None
        
        if frame_counter != 0 and fast_pgn.payload_length == 0:
            logger.debug(f"Ignoring frame {frame_counter} for PGN {pgn} as first frame has not been received.")
            return None
        
        # if this is the first frame of new sequence we will start over
        if frame_counter == 0 and sequence_counter != fast_pgn.sequence_counter:
            
            # Extract the total number of frames from the second-to-last byte
            total_bytes = can_data[-2]
           
            # Start a new pgn hass structure 
        
            fast_pgn.payload_length = total_bytes
            fast_pgn.sequence_counter = sequence_counter
            fast_pgn.bytes_stored = 0  # Reset bytes stored for a new message
            fast_pgn.frames.clear()  # Clear previous frames
                    
            # For the first frame, exclude the last 4 hex characters (2 bytes) from the payload
            data_payload = can_data[:-2]
            
        else:       
            if sequence_counter != fast_pgn.sequence_counter:
                logger.debug(f"Ignoring frame {sequence_counter} for PGN {pgn} as it does not match current sequence.")
                return None
            elif frame_counter in fast_pgn.frames:
                logger.debug(f"Frame {frame_counter} for PGN {pgn} is already stored.")
                return None
            else:
                # For subsequent frames, exclude the last byte from the payload
                data_payload = can_data[:-1]
        
        byte_length = len(data_payload)

        # Store the frame data
        fast_pgn.frames[frame_counter] = data_payload
        fast_pgn.bytes_stored += byte_length  # Update the count of bytes stored
        
        # Log the extracted values
        logger.debug(f"Sequence Counter: {sequence_counter}, Frame Counter: {frame_counter}")
        
        if total_bytes is not None:
            logger.debug(f"Total Payload Bytes: {total_bytes}")

        logger.debug(f"Orig Payload (hex): {can_data}, Data Payload (hex): {data_payload}")
        
        logger.debug("PGN Data: %s", fast_pgn)
        
        # Check if all expected bytes have been stored
        if fast_pgn.bytes_stored >= fast_pgn.payload_length:
            
            logger.debug("All Fast packet frames collected for PGN: %d", pgn)

            # All data for this PGN has been received, proceed to publish
            combined_payload = bytes([b for idx in sorted(fast_pgn.frames) for b in fast_pgn.frames[idx][::-1]])[::-1]
            
            nmea = None
            if combined_payload is not None:
                logger.debug(f"Combined Payload (hex): {combined_payload})")
                nmea = self._call_decode_function(pgn, priority, src, dest, timestamp, combined_payload)

            # Reset the structure for this PGN
            del self.data[fast_packet_key]
            return nmea
        else:
            logger.debug(f"Waiting for {fast_pgn.payload_length - fast_pgn.bytes_stored} more bytes.")
            return None

    def decode_actisense_string(self, actisense_string: str) -> NMEA2000Message | None:
        """Process an Actisense packet string and extract the PGN, source ID, and CAN data. Based on: https://actisense.com/knowledge-base/nmea-2000/w2k-1-nmea-2000-to-wifi-gateway/nmea-2000-ascii-output-format/"""
        # Split the Actisense string by spaces
        parts = actisense_string.split()
        
        if len(parts) < 3:
            raise ValueError("Invalid Actisense string format")
        
        if not parts[0].startswith("A"):
            raise ValueError("Invalid format: should start with 'A'")
    
        # Extract the timestamp from the first part
        seconds, milliseconds = map(int, parts[0][1:].split("."))
        offset = timedelta(seconds=seconds, milliseconds=milliseconds)
        timestamp = datetime.now() + offset

        # Extract the priority, destination, and source from the second part
        n = int(parts[1], 16)
        priority = n & 0xF
        dest = (n >> 4) & 0xFF
        src = (n >> 12) & 0xFF
        
        # Extract the PGN from the third part
        pgn = int(parts[2], 16)
        
        # Extract the CAN data from the remaining parts
        # Convert to bytes
        bytes_data = bytes.fromhex(parts[3])

        # Reverse the byte order
        reversed_bytes = bytes_data[::-1]

        # Log the extracted information
        logger.debug(f"Priority: {priority}, Destination: {dest}, Source: {src}, PGN: {pgn}, CAN Data: {reversed_bytes}")
        
        return self._decode(pgn, priority, src, dest, timestamp, bytes(reversed_bytes), True)

    def decode_yacht_devices_string(self, yd_string: str) -> NMEA2000Message | None:
        """Process an Yacht Devices string and extract the PGN, source ID, and CAN data. Based on: https://www.yachtd.com/downloads/ydwg02.pdf page 62-63"""
        # Split the Actisense string by spaces
        parts = yd_string.split()
        
        if len(parts) < 4:
            raise ValueError("Invalid Yacht Devices string format")
        
        if parts[1] != "R":
            raise ValueError("Invalid format: 2nd part should be 'R'")
    
        # Extract the timestamp from the first part
        timestamp = datetime.strptime(parts[0], "%H:%M:%S.%f")

        # Extract the PGN, priority, destination, and source from the second part
        msgid = int(parts[2], 16)
        pgn_id, source_id, dest, priority = NMEA2000Decoder._extract_header(msgid)
        
        # Extract the CAN data from the remaining parts
        can_data = parts[3:][::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]

        # Log the extracted information
        logger.debug(f"Priority: {priority}, Destination: {dest}, Source: {source_id}, PGN: {pgn_id}, CAN Data: {can_data_bytes}")
        
        return self._decode(pgn_id, priority, source_id, dest, timestamp, bytes(can_data_bytes))

    def decode_basic_string(self, basic_string: str, already_combined: bool = False) -> NMEA2000Message | None:
        """Process an Actisense packet string and extract the PGN, source ID, and CAN data."""
        # Split the Actisense string by spaces
        parts = basic_string.split(",")
        
        if len(parts) < 7: # should have at least one data bytes probably
            raise ValueError("Invalid string format")
        
        # Extract the fields
        if parts[0].endswith("Z"):
            timestamp = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%S.%fZ")
        else:
            timestamp = datetime.strptime(parts[0], "%Y-%m-%d-%H:%M:%S.%f")
        priority = int(parts[1])
        pgn_id = int(parts[2])
        src = int(parts[3])
        dest = int(parts[4])
        length = int(parts[5])
        # Extract the CAN data from the remaining parts
        can_data = parts[6:6 + length][::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]
        # Log the extracted information
        logger.debug(f"Priority: {priority}, Destination: {dest}, Source: {src}, PGN: {pgn_id}, CAN Data: {can_data_bytes}")
        
        # not calling _decode as in this format the fast frames are already combined
        return self._decode(pgn_id, priority, src, dest, timestamp, bytes(can_data_bytes), already_combined)

    @staticmethod
    def _extract_header(frame_id_int: int) -> Tuple[int, int, int, int]:
        """
        Extracts PGN, source ID, destination, and priority from a 29-bit CAN frame ID.
        Returns a tuple of (pgn_id, source_id, dest, priority).
        based on the 29 bits (ID0 - ID28) in https://canboat.github.io/canboat/canboat.html
        """
        source_id = frame_id_int & 0xFF             # bits 0-7 = 8 bits
        pgn_id_raw = (frame_id_int >> 8) & 0x3FFFF  # bits 8-25 = 18 bits
        priority = (frame_id_int >> 26) & 0x07      # bits 26-28 = 3 bits

        dp = (pgn_id_raw >> 16) & 0x3    # bits 16-17
        pf = (pgn_id_raw >> 8) & 0xFF    # bits 8-15
        ps = pgn_id_raw & 0xFF           # bits 0-7

        if pf < 0xF0:
            # PDU1 format: PS is destination address
            dest = ps
            pgn_id = (dp << 16) | (pf << 8)
        else:
            # PDU2 format: broadcast, destination is always 255
            dest = 255
            pgn_id = (dp << 16) | (pf << 8) | ps

        return pgn_id, source_id, dest, priority

    def decode_tcp(self, packet: bytes) -> NMEA2000Message | None:
        """Tested with ECAN devices. Process a single packet and extract the PGN, source ID, and CAN data."""
        
        # First byte has the data length in the lowest 4 bits
        type_byte = packet[0]
        data_length = type_byte & 0x0F  # last 4 bits represent the data length
        
        # Extract the frame ID
        frame_id = packet[1:5]      
        # Convert frame_id bytes to an integer
        frame_id_int = int.from_bytes(frame_id, byteorder='big')        
        # Parse it
        pgn_id, source_id, dest, priority = NMEA2000Decoder._extract_header(frame_id_int)

        # Extract and reverse the CAN data
        can_data = packet[5:5 + data_length][::-1]
               
        # Log the extracted information including the combined string
        logger.debug("PGN ID: %s, Frame ID: %s, CAN Data: %s, Source ID: %s",
            pgn_id,
            binascii.hexlify(frame_id).decode('ascii'),
            can_data,
            source_id)
        
        return self._decode(pgn_id, priority, source_id, dest, datetime.now(), bytes(can_data))

    def decode_usb(self, packet: bytes) -> NMEA2000Message | None:
        """Tested with Waveshare-usb-a device. Process a single packet and extract the PGN, source ID, and CAN data."""
        if packet[0] != 0xaa or packet[-1 ] != 0x55:
            raise Exception ("Packet does not have the right prefix and suffix")
        
        if len(packet) < 2 + 4 + 1: # 2 headers, 4 id, 1 data
            raise Exception ("Packet is too short")    
        
        # First byte has the data length in the lowest 4 bits
        type_byte = packet[1]
        data_length = type_byte & 0x0F  # last 4 bits represent the data length
        
        # Extract the frame ID
        frame_id = packet[2:6]        
        # Convert frame_id bytes to an integer
        frame_id_int = int.from_bytes(frame_id, byteorder='little')
        # Parse it
        pgn_id, source_id, dest, priority = NMEA2000Decoder._extract_header(frame_id_int)

        # Extract and reverse the CAN data
        can_data = packet[6:6 + data_length][::-1]
               
        # Log the extracted information including the combined string
        logger.debug("PGN ID: %s, Frame ID: %s, CAN Data: %s, Source ID: %s",
            pgn_id,
            binascii.hexlify(frame_id).decode('ascii'),
            can_data,
            source_id)
        
        return self._decode(pgn_id, priority, source_id, dest, datetime.now(), bytes(can_data))

    @staticmethod
    def _isFastPGN(pgn_id: int) -> bool:
        is_fast_func_name = f'is_fast_pgn_{pgn_id}'
        is_fast_func = globals().get(is_fast_func_name)

        if is_fast_func:
            is_fast = is_fast_func()
            logger.info(f"Is fast PGN: {is_fast}")
            return is_fast
        else:
            raise ValueError(f"No function found for PGN: {pgn_id}")

    def _decode(self, pgn_id: int, priority: int, source_id: int, destination_id: int, timestamp: datetime, can_data: bytes, already_combined: bool = False) -> NMEA2000Message | None:
        """Decode a single PGN message."""

        # Check if the PGN should be excluded or included
        if pgn_id in self.exclude_pgns:
            logger.debug(f"Excluding PGN: {pgn_id}")
            return None
        if len(self.include_pgns) > 0 and pgn_id not in self.include_pgns:
            logger.debug(f"Excluding PGN: {pgn_id}")
            return None

        is_fast = False
        if not already_combined:
            is_fast = NMEA2000Decoder._isFastPGN(pgn_id)

        if (is_fast):
            return self._decode_fast_message(pgn_id, priority, source_id, destination_id, timestamp, can_data)
        else:
            return self._call_decode_function(pgn_id, priority, source_id, destination_id, timestamp, can_data)

    def _call_decode_function(self, pgn:int, priority: int, src: int, dest: int, timestamp: datetime, data:bytes) -> NMEA2000Message:
        decode_func_name = f'decode_pgn_{pgn}'
        decode_func = globals().get(decode_func_name)

        if not decode_func:
            raise ValueError(f"No decoding function found for PGN: {pgn}")

        nmea2000Message = decode_func(int.from_bytes(data, "big"))
        nmea2000Message.add_data(src, dest, priority, timestamp)
        nmea2000Message.apply_preferred_units(self.preferred_units)
        sys.stdout.write(nmea2000Message.to_string_test_style()+"\n")
        if self.dump_to_folder is not None:
            str = nmea2000Message.to_json()
            filename = f"nmea_{nmea2000Message.PGN}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
            with open(os.path.join(self.dump_to_folder, filename), 'w') as f:
                f.write(str)
        return nmea2000Message
