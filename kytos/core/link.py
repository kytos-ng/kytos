"""Module with all classes related to links.

Links are low level abstractions representing connections between two
interfaces.
"""
import json
import operator
from collections import OrderedDict
from functools import reduce

from kytos.core.common import EntityStatus, GenericEntity
from kytos.core.events import KytosEvent
from kytos.core.exceptions import KytosLinkCreationError
from kytos.core.id import LinkID
from kytos.core.interface import Interface
from kytos.core.tag_capable import TAGCapable


class Link(GenericEntity, TAGCapable):
    """Define a link between two Endpoints."""

    status_funcs = OrderedDict()
    status_reason_funcs = OrderedDict()

    def __init__(self, endpoint_a, endpoint_b):
        """Create a Link instance and set its attributes.

        Two kytos.core.interface.Interface are required as parameters.
        """
        if endpoint_a is None:
            raise KytosLinkCreationError("endpoint_a cannot be None")
        if endpoint_b is None:
            raise KytosLinkCreationError("endpoint_b cannot be None")
        self._id = LinkID(endpoint_a.id, endpoint_b.id)
        if self._id.interfaces[0] == endpoint_b.id:
            self.endpoint_a: Interface = endpoint_b
            self.endpoint_b: Interface = endpoint_a
        else:
            self.endpoint_a: Interface = endpoint_a
            self.endpoint_b: Interface = endpoint_b

        TAGCapable.__init__(self, {}, {})
        GenericEntity.__init__(self)

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"Link({self.endpoint_a!r}, {self.endpoint_b!r}, {self.id})"

    @classmethod
    def register_status_func(cls, name: str, func):
        """Register status func given its name and a callable at setup time."""
        cls.status_funcs[name] = func

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

    def is_enabled(self):
        """Override the is_enabled method.

        We consider a link enabled when all the interfaces are enabled.

        Returns:
            boolean: True if both interfaces are enabled, False otherwise.

        """
        return (self._enabled and self.endpoint_a.is_enabled() and
                self.endpoint_b.is_enabled())

    def is_active(self):
        """Override the is_active method.

        We consider a link active whether all the interfaces are active.

        Returns:
            boolean: True if the interfaces are active, othewrise False.

        """
        return (self._active and self.endpoint_a.is_active() and
                self.endpoint_b.is_active())

    def __eq__(self, other):
        """Check if two instances of Link are equal."""
        return self.id == other.id

    @property
    def id(self):  # pylint: disable=invalid-name
        """Return id from Link intance.

        Returns:
            string: link id.

        """
        return self._id

    def notify_tag_listeners(self, controller):
        """Notify link available tags"""
        name = "kytos/core.link_tags"
        content = {"link": self}
        event = KytosEvent(name=name, content=content)
        controller.buffers.app.put(event)

    def as_dict(self):
        """Return the Link as a dictionary."""
        return {
            'id': self.id,
            'endpoint_a': self.endpoint_a.as_dict(),
            'endpoint_b': self.endpoint_b.as_dict(),
            'metadata': self.get_metadata_as_dict(),
            'active': self.is_active(),
            'enabled': self.is_enabled(),
            'status': self.status.value,
            'status_reason': sorted(self.status_reason),
        }

    def as_json(self):
        """Return the Link as a JSON string."""
        return json.dumps(self.as_dict())

    @classmethod
    def from_dict(cls, link_dict):
        """Return a Link instance from python dictionary."""
        return cls(link_dict.get('endpoint_a'),
                   link_dict.get('endpoint_b'))
