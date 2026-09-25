"""Sources Cairn can read that are not the local disk.

Every connector goes through the same permission layer and the same activity
log as everything else, so adding one never adds a new way of asking for
consent - and never adds a place where an action can happen unrecorded.
"""

from cairn.connectors.base import Connector, NotConnected, describe, registry

__all__ = ["Connector", "NotConnected", "describe", "registry"]
