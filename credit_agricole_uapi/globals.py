import threading
import time
from enum import Enum, auto


class RebootState(Enum):
    AVAILABLE = auto()
    UNAVAILABLE = auto()
    REBOOTING = auto()


class RebootLocker:
    def __init__(self):
        self.state: RebootState = RebootState.AVAILABLE
        self._lock: threading.Lock = threading.Lock()

    def disable_reboot(self):
        while True:
            with self._lock:
                if self.state != RebootState.REBOOTING:
                    self.state = RebootState.UNAVAILABLE
                    break
            time.sleep(0.1)

    def enable_reboot(self):
        with self._lock:
            self.state = RebootState.AVAILABLE

    def set_rebooting(self):
        with self._lock:
            self.state = RebootState.REBOOTING

    def reboot_is_available(self) -> bool:
        with self._lock:
            return self.state == RebootState.AVAILABLE


reboot_lock: RebootLocker = RebootLocker()
