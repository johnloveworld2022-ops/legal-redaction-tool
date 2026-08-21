import json
from pathlib import Path

from cryptography.fernet import Fernet

from core.subprocess_utils import run_subprocess

# `security find-generic-password` exit code for "the specified item
# could not be found in the keychain" -- confirmed empirically. Any OTHER
# non-zero code (locked keychain, denied access prompt, transient error)
# must be treated as a hard failure, never conflated with "no key yet".
_KEYCHAIN_ITEM_NOT_FOUND = 44

# Keychain access is normally near-instant; this only needs to be long
# enough for a user to notice and respond to a one-time access-prompt
# dialog, while still guaranteeing the GUI can't hang forever on it.
_KEYCHAIN_TIMEOUT_SECONDS = 30


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
        """Raises RuntimeError (not just returns/regenerates) on any
        Keychain failure other than a genuinely-missing item. Conflating
        "locked keychain" / "access prompt denied" with "key doesn't exist
        yet" would fall through to generating and writing a brand-new key
        via -U (update-if-exists), silently overwriting -- and
        permanently orphaning -- a real existing key and the
        mapping.json.enc encrypted under it. Found via external security
        review; see grill-report-2026-08-21.md.
        """
        result = run_subprocess(
            ["security", "find-generic-password", "-s", self.keychain_service,
             "-a", self.account, "-w"],
            capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            return result.stdout.strip().encode()
        if result.returncode != _KEYCHAIN_ITEM_NOT_FOUND:
            raise RuntimeError(
                f"读取钥匙串失败(退出码 {result.returncode}): {result.stderr.strip()}\n"
                "可能是钥匙串被锁定,或访问请求被拒绝。为避免覆盖已有的加密密钥,"
                "已停止处理——请解锁钥匙串或允许访问后重试。"
            )

        key = Fernet.generate_key()
        run_subprocess(
            ["security", "add-generic-password", "-s", self.keychain_service,
             "-a", self.account, "-w", key.decode(), "-U"],
            check=True, capture_output=True, timeout=_KEYCHAIN_TIMEOUT_SECONDS,
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
        run_subprocess(
            ["security", "delete-generic-password", "-s", self.keychain_service,
             "-a", self.account],
            capture_output=True, timeout=_KEYCHAIN_TIMEOUT_SECONDS,
        )
