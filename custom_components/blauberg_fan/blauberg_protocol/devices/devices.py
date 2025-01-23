from collections.abc import Mapping
from .blauberg_device import BlaubergDevice
from .smart_wifi import smart_wifi
from .bodo_supreme import bodo_supreme

devices: Mapping[int, BlaubergDevice] = {0x600: smart_wifi, 0xD00: bodo_supreme}
