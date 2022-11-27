
from __future__ import annotations
from typing import Optional, Mapping
from .packet import Packet, Section, ExpandingSection
import socket

import logging
LOG = logging.getLogger(__name__)

BUFFER_SIZE = 4096


class BlaubergProtocol():
    """Utility class to communicate with blauberg wifi protocol for their fans"""

    HEADER = Section(0xFDFD)
    PROTOCOL_TYPE = Section(0x02)
    CHECKSUM = Section.Template(2)
    LEAD_INDICATOR = Section(0xFF)
    INVALID = Section(0xFD)
    DYNAMIC_VAL = Section(0xFE)
    BLANK_BYTE = ExpandingSection()

    DEFAULT_PORT = 4000
    DEFAULT_TIMEOUT = 1
    DEFAULT_PWD = "1111"
    DEFAULT_DEVICE_ID = "DEFAULT_DEVICEID"

    class FUNC:
        Template = Section.Template(1)
        R = Section(0x01)
        RW = Section(0x03)

    def __init__(self,
                 host: str,
                 port: int = DEFAULT_PORT,
                 password: str = DEFAULT_PWD,
                 device_id: str = DEFAULT_DEVICE_ID,
                 timeout: float = DEFAULT_TIMEOUT):
        self._host = host
        self._port = port
        self._password = password
        self._device_id = device_id
        self._pwd_size = Section(len(password))
        self._id_size = Section(len(device_id))
        if self._id_size == 0:
            raise ValueError("device id can not be blank")
        self._timeout = timeout

    @property
    def device_id(self):
        return self._device_id

    def _protocol(self) -> Packet:
        protocol = [self.HEADER, self. PROTOCOL_TYPE, self._id_size, Section.Template(self._id_size.value), self._pwd_size, Section.Template(
            self._pwd_size.value), self.FUNC.Template, ExpandingSection(), self.CHECKSUM]
        if self._pwd_size.value == 0:
            # remove password section if password is blank
            protocol.pop(5)
        return Packet(protocol)

    def _response(self) -> Packet:
        return Packet(
            [self.HEADER, self.PROTOCOL_TYPE, self._id_size, Section.Template(
                self._id_size.value), self._pwd_size, self.FUNC.Template, ExpandingSection(), self.CHECKSUM]
        )

    def _connect(self) -> socket.socket:
        conn = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        conn.settimeout(self._timeout)
        conn.connect((self._host, self._port))
        return conn

    def _communicate(self, data: bytes) -> bytes:
        conn = self._connect()
        conn.sendall(data)
        response = bytes()
        try:
            response = conn.recv(BUFFER_SIZE)
        except socket.timeout:
            LOG.error("timeout")
        conn.close()
        return response

    @staticmethod
    def _swap_high_low(value: int, swap_size: int = 8) -> int:
        return (value << swap_size & int('1'*swap_size+'0'*swap_size, 2) | value >> swap_size & int('0'*swap_size+'1'*swap_size, 2))

    def _checksum(self, data: Packet) -> Section:
        check_sum = sum(data.to_bytes())
        return Section(self._swap_high_low(check_sum), 2)

    def _command(self, function: Section, data: Packet) -> Packet:
        index: int = 3  # skip header and protocol type since they are immutable
        command = self._protocol()
        command[index].set_bytes(bytes(self._device_id, 'utf-8'))
        index += 1
        # duplicate code with _protocol, added for readability concerns
        command[index] = self._pwd_size
        if self._pwd_size.value != 0:
            index += 1
            command[index].set_bytes(bytes(self._password, 'utf-8'))
        index += 1
        command[index] = function
        index += 1
        command[index] = Section(data.to_int(), data.byte_size())
        index += 1
        command[index] = self._checksum(Packet(command[1:-1]))
        return command

    def _communicate_block(self, function: Section, data: Packet) -> Section:
        LOG.info("constructing command from function:" +
                 str(function)+" data packet:" + str(data))
        command = self._command(function, data)
        LOG.info("sending command:" + str(command))
        raw_response = self._communicate(command.to_bytes())
        LOG.info("received raw response:" + str(raw_response))
        if len(raw_response) == 0:
            return self.BLANK_BYTE

        # Exclude checksum due to data section being expandible
        response = self._response().decode(raw_response[:-2])
        LOG.info("parsed raw response:" + str(response))

        actual_check_sum = self.CHECKSUM.set_bytes(raw_response[-2:]).value
        expected_check_sum = self._checksum(Packet(response[1:-1])).value
        if actual_check_sum != expected_check_sum:
            LOG.warn("invalid checksum response: expected: " +
                     str(expected_check_sum) + " actual: " + str(actual_check_sum))

        return response[-2]

    def _decode_data(self, raw_data: bytes) -> dict[int, Optional[int]]:
        values: dict[int, Optional[int]] = {}
        lead_byte = bytes()
        index = 0
        while index < len(raw_data):
            func = raw_data[index]
            if func == self.LEAD_INDICATOR.value:
                index += 1
                lead_byte = bytes([raw_data[index]])
                index += 1
            elif func == self.INVALID.value:
                index += 1
                tail_byte = bytes([raw_data[index]])
                index += 1
                param = Section.Template(2).set_bytes(
                    lead_byte+tail_byte).value
                if param not in values:
                    values[param] = None
            elif func == self.DYNAMIC_VAL.value:
                index += 1
                byte_length = raw_data[index]
                index += 1
                if (index+byte_length) > len(raw_data):
                    LOG.warn(
                        "byte length given is bigger than length of remaining bytes")
                    return values
                tail_byte = bytes([raw_data[index]])
                index += 1
                param = Section.Template(2).set_bytes(
                    lead_byte+tail_byte).value
                dynamic_part = raw_data[index:(index+byte_length)]
                value = Section.Template(
                    byte_length).set_bytes(dynamic_part).value
                values[param] = value
                index += byte_length
            else:
                tail_byte = bytes([raw_data[index]])
                index += 1
                param = Section.Template(2).set_bytes(
                    lead_byte+tail_byte).value
                value = raw_data[index]
                index += 1
                values[param] = value
        return values

    def _construct_command_block(self, parameters: Mapping[int, Optional[int]]) -> Packet:
        params = list(parameters.keys())
        params.sort()
        params_by_lead: dict[int, list[int]] = {}
        for param in params:
            raw = Section(param, 2).to_bytes()
            lead = raw[0]
            tail = raw[1]
            if lead not in params_by_lead:
                params_by_lead[lead] = []
            params_by_lead[lead].append(tail)

        data_packet = Packet()
        for lead in params_by_lead:
            data_packet.append(self.LEAD_INDICATOR)
            data_packet.append(Section(lead))
            for tail in params_by_lead[lead]:
                param = Section(byte_size=2).set_bytes(
                    Section(lead).to_bytes()+Section(tail).to_bytes()).value
                val = parameters[param]
                if val is not None:
                    data_packet.append(self.DYNAMIC_VAL)
                    value_sec = Section(val)
                    data_packet.append(Section(value_sec.byte_size))
                    data_packet.append(Section(tail))
                    data_packet.append(value_sec)
                else:
                    data_packet.append(Section(tail))
        return data_packet

    def read_params(self, parameters: list[int]) -> dict[int, Optional[int]]:
        params = {}
        for param in parameters:
            params[param] = None
        data_response = self._communicate_block(
            self.FUNC.R, self._construct_command_block(params))
        raw_data = data_response.to_bytes()
        return self._decode_data(raw_data)

    def read_param(self, param: int) -> int:
        params = self.read_params([param])
        if param not in params:
            return 0
        return params[param] or 0

    def write_params(self, parameters: Mapping[int, int]) -> dict[int, Optional[int]]:
        data_response = self._communicate_block(
            self.FUNC.RW, self._construct_command_block(parameters))
        raw_data = data_response.to_bytes()
        return self._decode_data(raw_data)

    def write_param(self, parameter: int, value: int) -> int:
        data_response = self._communicate_block(
            self.FUNC.RW, Packet([Section(parameter), Section(value)]))
        raw_data = data_response.to_bytes()
        return self._decode_data(raw_data)[parameter] or 0

    def device_type(self, type_parameter: int = 0xB9) -> int:
        return self.read_param(type_parameter)
