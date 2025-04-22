"""Module with main classes related to Interfaces."""
import json
import logging
import operator
from collections import OrderedDict
from enum import Enum
from functools import reduce
from typing import Union

from pyof.v0x01.common.phy_port import Port as PortNo01
from pyof.v0x01.common.phy_port import PortFeatures as PortFeatures01
from pyof.v0x04.common.port import PortFeatures as PortFeatures04
from pyof.v0x04.common.port import PortNo as PortNo04

from kytos.core.common import EntityStatus, GenericEntity
from kytos.core.events import KytosEvent
from kytos.core.helpers import now
from kytos.core.id import InterfaceID
from kytos.core.tag_capable import TAGCapable

__all__ = ('Interface',)

LOG = logging.getLogger(__name__)


class TAGType(Enum):
    """Class that represents a TAG Type."""

    VLAN = 'vlan'
    VLAN_QINQ = 'vlan_qinq'
    MPLS = 'mpls'


class TAG:
    """Class that represents a TAG."""

    def __init__(self, tag_type: str, value: int):
        self.tag_type = TAGType(tag_type).value
        self.value = value

    def __eq__(self, other):
        if not other:
            return False
        return self.tag_type == other.tag_type and self.value == other.value

    def as_dict(self):
        """Return a dictionary representating a tag object."""
        return {'tag_type': self.tag_type, 'value': self.value}

    @classmethod
    def from_dict(cls, tag_dict):
        """Return a TAG instance from python dictionary."""
        return cls(tag_dict.get('tag_type'), tag_dict.get('value'))

    @classmethod
    def from_json(cls, tag_json):
        """Return a TAG instance from json."""
        return cls.from_dict(json.loads(tag_json))

    def as_json(self):
        """Return a json representating a tag object."""
        return json.dumps(self.as_dict())

    def __repr__(self):
        return f"TAG({self.tag_type!r}, {self.value!r})"


# pylint: disable=super-init-not-called
class TAGRange(TAG):
    """Class that represents an User-to-Network Interface with
     a tag value as a list."""

    def __init__(
        self,
        tag_type: str,
        value: list[list[int]],
        mask_list: list[Union[str, int]] = None
    ):
        self.tag_type = TAGType(tag_type).value
        self.value = value
        self.mask_list = mask_list or []

    def as_dict(self):
        """Return a dictionary representating a tag range object."""
        return {
            'tag_type': self.tag_type,
            'value': self.value,
            'mask_list': self.mask_list
        }


# pylint: disable=too-many-instance-attributes
class Interface(GenericEntity, TAGCapable):
    """Interface Class used to abstract the network interfaces."""

    status_funcs = OrderedDict()
    status_reason_funcs = OrderedDict()

    # pylint: disable=too-many-arguments
    def __init__(self, name, port_number, switch, address=None, state=None,
                 features=None, speed=None, config=None):
        """Assign the parameters to instance attributes.

        Args:
            name (string): name from this interface.
            port_number (int): port number from this interface.
            switch (:class:`~.core.switch.Switch`): Switch with this interface.
            address (|hw_address|): Port address from this interface.
            state (|port_stats|): Port Stat from interface. It will be
            deprecated.
            features (|port_features|): Port feature used to calculate link
                utilization from this interface. It will be deprecated.
            speed (int, float): Interface speed in bytes per second. Defaults
                to what is informed by the switch. Return ``None`` if not set
                and switch does not inform the speed.
            config(|port_config|): Port config used to indicate interface
                behavior. In general, the port config bits are set by the
                controller and are not changed by the switch. Options
                are: administratively down, ignore received packets, drop
                forwarded packets, and/or do not send packet-in messages.

        Attributes:
            available_tags (dict[str, list[list[int]]]): Contains the available
                tags integers in the current interface, the availability is
                represented as a list of ranges. These ranges are
                [inclusive, inclusive]. For example, [1, 5] represents
                [1, 2, 3, 4, 5].
            tag_ranges (dict[str, list[list[int]]]): Contains restrictions for
                available_tags. The list of ranges is the same type as in
                available_tags. Setting a new tag_ranges will required for
                available_tags to be resize.

        """
        self.name = name
        self.port_number = int(port_number)
        self.switch = switch
        self.address = address
        self.state = state
        self.features = features
        self.config = config
        self.nni = False
        self.endpoints = []
        self.stats = None
        self.link = None
        self.lldp = True
        self._id = InterfaceID(switch.id, port_number)
        self._custom_speed = speed

        TAGCapable.__init__(
            self,
            {
                "vlan": [[1, 4094]],
                # "vlan_qinq": [[1, 4094]],
                # "mpls": [[1, 1048575]],
            },
            {
                "vlan": ["untagged", "any"],
            },
        )
        GenericEntity.__init__(self)

    def __repr__(self):
        return f"Interface('{self.name}', {self.port_number}, {self.switch!r})"

    def __eq__(self, other):
        """Compare Interface class with another instance."""
        if isinstance(other, str):
            return self.address == other
        if isinstance(other, Interface):
            return self.port_number == other.port_number and \
                self.switch.dpid == other.switch.dpid
        return False

    @property
    def id(self):  # pylint: disable=invalid-name
        """Return id from Interface instance.

        Returns:
            string: Interface id.

        """
        return self._id

    @property
    def uni(self):
        """Return if an interface is a user-to-network Interface."""
        return not self.nni

    @property
    def status(self):
        """Return the current status of the Entity."""
        state = super().status
        if state == EntityStatus.DISABLED:
            return state

        for status_func in self.status_funcs.values():
            if status_func(self) == EntityStatus.DOWN:
                return EntityStatus.DOWN
        return state

    @classmethod
    def register_status_func(cls, name: str, func):
        """Register status func given its name and a callable at setup time."""
        cls.status_funcs[name] = func

    @classmethod
    def register_status_reason_func(cls, name: str, func):
        """Register status reason func given its name
        and a callable at setup time."""
        cls.status_reason_funcs[name] = func

    @property
    def status_reason(self):
        """Return the reason behind the current status of the entity."""
        return reduce(
            operator.or_,
            map(
                lambda x: x(self),
                self.status_reason_funcs.values()
            ),
            super().status_reason
        )

    def get_endpoint(self, endpoint):
        """Return a tuple with existent endpoint, None otherwise.

        Args:
            endpoint(|hw_address|, :class:`.Interface`): endpoint instance.

        Returns:
            tuple: A tuple with endpoint and time of last update.

        """
        for item in self.endpoints:
            if endpoint == item[0]:
                return item
        return None

    def add_endpoint(self, endpoint):
        """Create a new endpoint to Interface instance.

        Args:
            endpoint(|hw_address|, :class:`.Interface`): A target endpoint.
        """
        exists = self.get_endpoint(endpoint)
        if not exists:
            self.endpoints.append((endpoint, now()))

    def delete_endpoint(self, endpoint):
        """Delete a existent endpoint in Interface instance.

        Args:
            endpoint (|hw_address|, :class:`.Interface`): A target endpoint.
        """
        exists = self.get_endpoint(endpoint)
        if exists:
            self.endpoints.remove(exists)

    def update_endpoint(self, endpoint):
        """Update or create new endpoint to Interface instance.

        Args:
            endpoint(|hw_address|, :class:`.Interface`): A target endpoint.
        """
        exists = self.get_endpoint(endpoint)
        if exists:
            self.delete_endpoint(endpoint)
        self.add_endpoint(endpoint)

    def update_link(self, link):
        """Update link for this interface in a consistent way.

        Verify of the other endpoint of the link has the same Link information
        attached to it, and change it if necessary.

        Warning: This method can potentially change information of other
        Interface instances. Use it with caution.
        """
        if self not in (link.endpoint_a, link.endpoint_b):
            return False

        if self.link is None or self.link != link:
            self.link = link

        if link.endpoint_a == self:
            endpoint = link.endpoint_b
        else:
            endpoint = link.endpoint_a

        if endpoint.link is None or endpoint.link != link:
            endpoint.link = link

        return True

    @property
    def speed(self):
        """Return the link speed in bytes per second, None otherwise.

        If the switch was disconnected, we have :attr:`features` and speed is
        still returned for common values between v0x01 and v0x04. For specific
        v0x04 values (40 Gbps, 100 Gbps and 1 Tbps), the connection must be
        active so we can make sure the protocol version is v0x04.

        Returns:
            int, None: Link speed in bytes per second or ``None``.

        """
        speed = self.get_of_features_speed()

        if speed is not None:
            return speed

        if self._custom_speed is not None:
            return self._custom_speed

        if self._is_v0x04() and self.port_number == PortNo04.OFPP_LOCAL:
            return 0

        if not self._is_v0x04() and self.port_number == PortNo01.OFPP_LOCAL:
            return 0

        # Warn unknown speed
        # Use shorter switch ID with its beginning and end
        if isinstance(self.switch.id, str) and len(self.switch.id) > 20:
            switch_id = self.switch.id[:3] + '...' + self.switch.id[-3:]
        else:
            switch_id = self.switch.id
        LOG.warning("Couldn't get port %s speed, sw %s, feats %s",
                    self.port_number, switch_id, self.features)

        return None

    def set_custom_speed(self, bytes_per_second):
        """Set a speed that overrides switch OpenFlow information.

        If ``None`` is given, :attr:`speed` becomes the one given by the
        switch.
        """
        self._custom_speed = bytes_per_second

    def get_custom_speed(self):
        """Return custom speed or ``None`` if not set."""
        return self._custom_speed

    def get_of_features_speed(self):
        """Return the link speed in bytes per second, None otherwise.

        If the switch was disconnected, we have :attr:`features` and speed is
        still returned for common values between v0x01 and v0x04. For specific
        v0x04 values (40 Gbps, 100 Gbps and 1 Tbps), the connection must be
        active so we can make sure the protocol version is v0x04.

        Returns:
            int, None: Link speed in bytes per second or ``None``.

        """
        speed = self._get_v0x01_v0x04_speed()
        # Don't use switch.is_connected() because we can have the protocol
        if speed is None and self._is_v0x04():
            speed = self._get_v0x04_speed()
        return speed

    def _is_v0x04(self):
        """Whether the switch is connected using OpenFlow 1.3."""
        return self.switch.is_connected() and \
            self.switch.connection.protocol.version == 0x04

    def _get_v0x01_v0x04_speed(self):
        """Check against all values of v0x01. They're part of v0x04."""
        fts = self.features
        pfts = PortFeatures01
        if fts and fts & pfts.OFPPF_10GB_FD:
            return 10 * 10**9 / 8
        if fts and fts & (pfts.OFPPF_1GB_HD | pfts.OFPPF_1GB_FD):
            return 10**9 / 8
        if fts and fts & (pfts.OFPPF_100MB_HD | pfts.OFPPF_100MB_FD):
            return 100 * 10**6 / 8
        if fts and fts & (pfts.OFPPF_10MB_HD | pfts.OFPPF_10MB_FD):
            return 10 * 10**6 / 8
        return None

    def _get_v0x04_speed(self):
        """Check against higher enums of v0x04.

        Must be called after :meth:`get_v0x01_speed` returns ``None``.
        """
        fts = self.features
        pfts = PortFeatures04
        if fts and fts & pfts.OFPPF_1TB_FD:
            return 10**12 / 8
        if fts and fts & pfts.OFPPF_100GB_FD:
            return 100 * 10**9 / 8
        if fts and fts & pfts.OFPPF_40GB_FD:
            return 40 * 10**9 / 8
        return None

    def get_hr_speed(self):
        """Return Human-Readable string for link speed.

        Returns:
            string: String with link speed. e.g: '350 Gbps' or '350 Mbps'.

        """
        speed = self.speed
        if speed is None:
            return ''
        speed *= 8
        if speed == 10**12:
            return '1 Tbps'
        if speed >= 10**9:
            return f"{round(speed / 10**9)} Gbps"
        return f"{round(speed / 10**6)} Mbps"

    def as_dict(self):
        """Return a dictionary with Interface attributes.

        Speed is in bytes/sec. Example of output (100 Gbps):

        .. code-block:: python3

            {'id': '00:00:00:00:00:00:00:01:2',
             'name': 'eth01',
             'port_number': 2,
             'mac': '00:7e:04:3b:c2:a6',
             'switch': '00:00:00:00:00:00:00:01',
             'type': 'interface',
             'nni': False,
             'uni': True,
             'speed': 12500000000,
             'metadata': {},
             'lldp': True,
             'active': True,
             'enabled': False,
             'status': 'DISABLED',
             'link': ""
            }

        Returns:
            dict: Dictionary filled with interface attributes.

        """
        iface_dict = {
            'id': self.id,
            'name': self.name,
            'port_number': self.port_number,
            'mac': self.address,
            'switch': self.switch.dpid,
            'type': 'interface',
            'nni': self.nni,
            'uni': self.uni,
            'speed': self.speed,
            'metadata': self.metadata,
            'lldp': self.lldp,
            'active': self.is_active(),
            'enabled': self.is_enabled(),
            'status': self.status.value,
            'status_reason': sorted(self.status_reason),
            'link': self.link.id if self.link else "",
        }
        if self.stats:
            iface_dict['stats'] = self.stats.as_dict()
        return iface_dict

    @classmethod
    def from_dict(cls, interface_dict):
        """Return a Interface instance from python dictionary."""
        return cls(interface_dict.get('name'),
                   interface_dict.get('port_number'),
                   interface_dict.get('switch'),
                   interface_dict.get('address'),
                   interface_dict.get('state'),
                   interface_dict.get('features'),
                   interface_dict.get('speed'))

    def as_json(self):
        """Return a json with Interfaces attributes.

        Example of output:

        .. code-block:: json

            {"mac": "00:7e:04:3b:c2:a6",
             "switch": "00:00:00:00:00:00:00:01",
             "type": "interface",
             "name": "eth01",
             "id": "00:00:00:00:00:00:00:01:2",
             "port_number": 2,
             "speed": "350 Mbps"}

        Returns:
            string: Json filled with interface attributes.

        """
        return json.dumps(self.as_dict())

    def notify_tag_listeners(self, controller):
        """Notify link available tags"""
        name = "kytos/core.interface_tags"
        content = {"interface": self}
        event = KytosEvent(name=name, content=content)
        controller.buffers.app.put(event)


class UNI:
    """Class that represents an User-to-Network Interface."""

    def __init__(
        self,
        interface: Interface,
        user_tag: Union[None, TAG, TAGRange]
    ):
        self.user_tag = user_tag
        self.interface = interface

    def __eq__(self, other):
        """Override the default implementation."""
        return (self.user_tag == other.user_tag and
                self.interface == other.interface)

    def _is_reserved_valid_tag(self) -> bool:
        """Check if TAG string is possible"""
        reserved_tag = {"any", "untagged"}
        if self.user_tag.value in reserved_tag:
            return True
        return False

    def is_valid(self):
        """Check if TAG is possible for this interface TAG pool."""
        if self.user_tag:
            tag = self.user_tag.value
            if isinstance(tag, str):
                return self._is_reserved_valid_tag()
            if isinstance(tag, int):
                with self.interface.tag_lock:
                    return self.interface.is_tag_available(
                        self.user_tag.tag_type,
                        tag,
                    )
        return True

    def as_dict(self):
        """Return a dict representating a UNI object."""
        return {
            'interface_id': self.interface.id,
            'tag': self.user_tag.as_dict() if self.user_tag else None
            }

    @classmethod
    def from_dict(cls, uni):
        """Return a Uni instance from python dictionary."""
        return cls(uni.get('interface'),
                   uni.get('user_tag'))

    def as_json(self):
        """Return a json representating a UNI object."""
        return json.dumps(self.as_dict())


class NNI:
    """Class that represents an Network-to-Network Interface."""

    def __init__(self, interface):
        self.interface = interface


class VNNI(NNI):
    """Class that represents an Virtual Network-to-Network Interface."""

    def __init__(self, service_tag, *args, **kwargs):
        self.service_tag = service_tag

        super().__init__(*args, **kwargs)
