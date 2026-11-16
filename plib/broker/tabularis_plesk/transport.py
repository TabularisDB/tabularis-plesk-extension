"""Linux socket ownership checks bind secrets to an already-connected runtime."""
import os
from pathlib import Path
import socket
import time


def tcp_address(address):
    host, port = address[:2]
    return socket.inet_aton(host)[::-1].hex().upper() + f':{port:04X}'


def owns_connected_peer(process, expected_uid, client_address, server_address, timeout=1.0):
    """Wait for accept(), then inspect the server endpoint of this exact TCP tuple.

    A successful check binds this established connection to the dedicated runtime UID.
    The known child must remain alive; no other service uses that UID.
    Replacing the listening port afterwards cannot replace that connection.
    """
    expected_local = tcp_address(server_address)
    expected_remote = tcp_address(client_address)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            if Path(f'/proc/{process.pid}').stat().st_uid != expected_uid:
                return False
            for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
                entry = line.split()
                if (entry[1] == expected_local and entry[2] == expected_remote
                    and entry[3] == '01' and entry[9] != '0' and int(entry[7]) == expected_uid):
                    return process.poll() is None
        except (OSError, IndexError):
            return False
        time.sleep(0.01)
    return False
