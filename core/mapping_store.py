import json
import subprocess
from pathlib import Path

from cryptography.fernet import Fernet


class MappingStore:
    """Encrypted, per-case placeholder<->real-name table.

    The mapping is itself a concentrated PII file (it's literally the key
    to reverse every redaction), so it never touches disk in plaintext.
    The symmetric key lives in the macOS login Keychain, scoped by
    ``keychain_service`` (recommended: one service string per case, e.g.
    ``"法律脱敏工具-案件-<案号>"``), so a key is created once per case and
    reused on every subsequent run rather than orphaning old mappings.
    """

    def __init__(self, path: Path, keychain_service: str, account: str = "mapping-key"):
        self.path = Path(path)
        self.keychain_service = keychain_service
        self.account = account

    def _get_or_create_key(self) -> bytes:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", self.keychain_service,
             "-a", self.account, "-w"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip().encode()

        key = Fernet.generate_key()
        subprocess.run(
            ["security", "add-generic-password", "-s", self.keychain_service,
             "-a", self.account, "-w", key.decode(), "-U"],
            check=True, capture_output=True,
        )
        return key

    def save(self, mapping: dict[str, str]) -> None:
        key = self._get_or_create_key()
        data = json.dumps(mapping, ensure_ascii=False).encode("utf-8")
        token = Fernet(key).encrypt(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(token)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        key = self._get_or_create_key()
        data = Fernet(key).decrypt(self.path.read_bytes())
        return json.loads(data.decode("utf-8"))

    def delete_key(self) -> None:
        subprocess.run(
            ["security", "delete-generic-password", "-s", self.keychain_service,
             "-a", self.account],
            capture_output=True,
        )
