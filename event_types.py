from PyQt6 import QtCore

class EventTypes:
    """Stores a string name for each event type.

    With PySide2 str() on the event type gives a nice string name,
    but with PyQt5 it does not. So this method works with both systems.
    """

    def __init__(self):
        """Create mapping for all known event types."""
        self.string_name = {}
        for name in vars(QtCore.QEvent):
            attribute = getattr(QtCore.QEvent, name)
            if type(attribute) == QtCore.QEvent.Type:
                self.string_name[attribute] = name

    def as_string(self, event: QtCore.QEvent.Type) -> str:
        """Return the string name for this event."""
        try:
            return self.string_name[event]
        except KeyError:
            return f"UnknownEvent:{event}"

if __name__ == "__main__":
    #print(vars(QtCore.QEvent.Type))

    event = QtCore.QEvent.Type.UpdateRequest
    print(event)
    print(event.type)
    event_str = EventTypes().as_string(event)
    print(event_str)
