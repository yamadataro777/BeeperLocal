"""RAM-only desktop session cache. Native Keychain remains the sole secret store."""
from collections import OrderedDict
from threading import RLock

from .native_keychain import KeychainStatusError


class KeychainSession:
    def __init__(self, backend):
        self.backend = backend
        self.values = OrderedDict()
        self.denied = {}
        self.lock = RLock()

    def _remember(self, key, value):
        self.values[key] = value
        self.values.move_to_end(key)
        while len(self.values) > 32:
            self.values.popitem(last=False)

    def _call(self, key, operation, *args):
        if key in self.denied:
            raise KeychainStatusError(self.denied[key])
        try:
            return operation(*args)
        except KeychainStatusError as exc:
            status = exc.args[0]
            if status in {-128, -25293, -25308}:
                self.denied[key] = status
            raise

    def get_password(self, service, account):
        key = (service, account)
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
                return self.values[key]
            value = self._call(key, self.backend.get_password, service, account)
            # Missing items can be created by the explicit login helper later.
            if value is not None:
                self._remember(key, value)
            return value

    def set_password(self, service, account, value):
        key = (service, account)
        with self.lock:
            if key in self.values and self.values[key] == value:
                return
            self.values.pop(key, None)
            self._call(key, self.backend.set_password, service, account, value)
            actual = self._call(key, self.backend.get_password, service, account)
            if actual != value:
                raise KeychainStatusError(-26275)
            self._remember(key, actual)

    def delete_password(self, service, account):
        key = (service, account)
        with self.lock:
            self.values.pop(key, None)
            self._call(key, self.backend.delete_password, service, account)

    def retry(self, service, account):
        """Only explicit user reconnection rechecks a cancelled OS request.

        Keep an already loaded DB key: reconnecting is not a key rotation.
        Invalidate provider credentials to pick up the native login helper.
        """
        with self.lock:
            self.values.pop((service, account), None)
            for key in list(self.denied):
                if key[0] == service and key[1] in {account, 'local-db-key-v1'}:
                    del self.denied[key]

    def clear(self):
        with self.lock:
            self.values.clear()
            self.denied.clear()
