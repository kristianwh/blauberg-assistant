from __future__ import annotations
from collections.abc import Mapping, Sequence, Callable
from typing import NamedTuple
from enum import Enum


class Purpose(str, Enum):
    """represents the purpose of a parameter"""

    POWER = "power"
    FAN_SPEED = "speed"
    MOISTURE_SENSOR = "moist"
    TEMPERATURE_SENSOR = "temp"
    PRESET = "preset"
    VERSION = "version"


class ComplexAction(NamedTuple):
    """represents an action that can be done on the fan, it is used to communicate home assistant interactions to the fan
    for parsing lambda function signatures int is used here instead of bytes since it is more practical for most purposes,
    if needed int can be converted into bytes with int.to_bytes function. response_parser can get unrequested
    (not included in the parameters list) values in the input mapping
    """

    # parameter numbers to be read, the response will be parsed with the response parser
    parameters: Sequence[int]
    # parses the response returned from the fan, used for parsing the read and write responses
    response_parser: Callable[[Mapping[int, int | None]], float | str | int | None]
    # parses the home assistant input to fan request values
    request_parser: Callable[[float | str | int | bool | None], Mapping[int, int]]


def SinglePointAction(param: int):
    """represents an action that can be performed on a single parameter, if mapping between home assistant and fan is 1-1 this function should be used"""
    return ComplexAction(
        parameters=[param],
        response_parser=lambda response: response[param],
        request_parser=lambda input: {param: variable_to_bytes(input)},
    )


class Component(Enum):
    BUTTON = 1
    SWITCH = 2
    SLIDER = 3
    DROPDOWN = 4


class OptionalAction(NamedTuple):
    """represents optional actions that can be added to home assistant but not enabled by default"""

    name: str
    identifier: str
    component: Component
    action: ComplexAction
    options: Sequence[str] | None = None  # only valid for dropdown
    maximum: int | None = None  # only valid for slider
    minimum: int | None = None  # only valid for slider


class BlaubergDevice(NamedTuple):
    """represents a blauberg device for home assistant
    it represents home assistant functions to device's parameters mapping
    and allows some custom logic to be implemented for mapping parameters with lambdas"""

    name: str
    parameter_map: Mapping[Purpose, ComplexAction]
    presets: Sequence[str]
    extra_parameters: Sequence[OptionalAction]
    attribute_map: Mapping[str, ComplexAction]


def variable_to_bytes(variable: float | str | int | bool | None) -> int:
    if variable is None:
        return -1
    if isinstance(variable, float):
        # since float is not supported by the blauberg fans, they are all converted to integers
        # now converting to float, as flexit fans support this. testing. should also differenciate between types of fans here if it works. TODO
        return float(variable)
    if isinstance(variable, str):
        return int.from_bytes(bytes(variable, "utf-8"), "big")
    if isinstance(variable, bool):
        return 1 if variable else 0
    return variable
