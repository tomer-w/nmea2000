import sys
import logging
import binascii
from .message import NMEA2000Message
from .pgns import *  # noqa: F403

logger = logging.getLogger(__name__)

class fast_pgn_metadata():
    def __init__(self) -> None:
        self.frames = {}
        self.payload_length = 0
        self.bytes_stored = 0
        self.sequence_counter = 0

    def __repr__(self):
        return f"<fast_pgn_metadata frames={len(self.frames)} payload_length={self.payload_length} bytes_stored={self.bytes_stored} sequence_counter={self.sequence_counter}>"

class NMEA2000Decoder():
    def __init__(self) -> None:
        self.data = {}

    def _decode_fast_message(self, pgn, priority, src, dest, can_data) -> NMEA2000Message:
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
        
        # Calculate data payload
        if frame_counter == 0:
            
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
                nmea = self._call_decode_function(pgn, priority, src, dest, combined_payload)

            # Reset the structure for this PGN
            del self.data[fast_packet_key]
            return nmea
        else:
            logger.debug(f"Waiting for {fast_pgn.payload_length - fast_pgn.bytes_stored} more bytes.")
            return None

    def decode_actisense_string(self, actisense_string: str) -> NMEA2000Message:
        """Process an Actisense packet string and extract the PGN, source ID, and CAN data."""
        # Split the Actisense string by spaces
        parts = actisense_string.split()
        
        if len(parts) < 2:
            raise ValueError("Invalid Actisense string format")
        
        # Extract the priority, destination, and source from the first part
        n = int(parts[0], 16)
        priority = n & 0xF
        dest = (n >> 4) & 0xFF
        src = (n >> 12) & 0xFF
        
        # Extract the PGN from the second part
        pgn = int(parts[1], 16)
        
        # Extract the CAN data from the remaining parts
        # Convert to bytes
        bytes_data = bytes.fromhex(parts[2])

        # Reverse the byte order
        reversed_bytes = bytes_data[::-1]

        # Log the extracted information
        logger.debug(f"Priority: {priority}, Destination: {dest}, Source: {src}, PGN: {pgn}, CAN Data: {reversed_bytes}")
        
        # not calling _decode as in this format the fast frames are already combined
        return self._call_decode_function(pgn, priority, src, dest, reversed_bytes)
        
    def decode_basic_string(self, basic_string: str) -> NMEA2000Message:
        """Process an Actisense packet string and extract the PGN, source ID, and CAN data."""
        # Split the Actisense string by spaces
        parts = basic_string.split(",")
        
        if len(parts) < 7: # should have at least one data bytes probably
            raise ValueError("Invalid string format")
        
        # Extract the fields
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
        return self._decode(pgn_id, priority, src, dest, can_data_bytes)

    def decode(self, packet: bytes) -> NMEA2000Message:
        """Process a single packet and extract the PGN, source ID, and CAN data."""
        
        # Extract the priority (first 3 bits) and data length (last 4 bits) from the type byte
        type_byte = packet[0]
        priority = (type_byte >> 5) & 0x07  # first 3 bits represent the priority
        data_length = type_byte & 0x0F  # last 4 bits represent the data length
        
        # Extract and reverse the frame ID
        frame_id = packet[1:5][::-1]
        
        # Convert frame_id bytes to an integer
        frame_id_int = int.from_bytes(frame_id, byteorder='big')
        
        # Extracting Source ID from the frame ID
        source_id = frame_id_int & 0xFF
        
        # Extracting PGN ID from the frame ID
        pgn_id = (frame_id_int >> 8) & 0x3FFFF  # Shift right by 8 bits and mask to 18 bits
        
        # Extract and reverse the CAN data
        can_data = packet[5:5 + data_length][::-1]
               
        # Log the extracted information including the combined string
        logger.debug("PGN ID: %s, Frame ID: %s, CAN Data: %s, Source ID: %s",
            pgn_id,
            binascii.hexlify(frame_id).decode('ascii'),
            can_data,
            source_id)
        
        return self._decode(pgn_id, priority, source_id, 255, can_data) # TODO: destination is hardcoded to 255

    def _decode(self, pgn_id: int, priority: int, source_id: int, destination_id: int, can_data: bytes) -> NMEA2000Message:
        is_fast_func_name = f'is_fast_pgn_{pgn_id}'
        is_fast_func = globals().get(is_fast_func_name)

        if is_fast_func:
            is_fast = is_fast_func()
            logger.info(f"Is fast PGN: {is_fast}")
        else:
            logger.error(f"No function found for PGN: {pgn_id}\n")
            return None

        if (is_fast):
            return self._decode_fast_message(pgn_id, priority, source_id, destination_id, can_data)
        else:
            return self._call_decode_function(pgn_id, priority, source_id, destination_id, can_data)

    def _call_decode_function(self, pgn:int, priority: int, src: int, dest: int, data:bytes) -> NMEA2000Message:
        decode_func_name = f'decode_pgn_{pgn}'
        decode_func = globals().get(decode_func_name)

        if not decode_func:
            raise ValueError(f"No function found for PGN: {pgn}")

        nmea2000Message = decode_func(int.from_bytes(data, "big"))
        nmea2000Message.add_data(src, dest, priority)
        sys.stdout.write(nmea2000Message.to_string_test_style()+"\n")
        return nmea2000Message
        
