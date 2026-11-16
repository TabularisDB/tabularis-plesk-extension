"""Drop all privilege in a fresh single-threaded process before executing Tabularis."""
import ctypes
import os
import resource
import sys


def main():
    uid, gid, memory = map(int, sys.argv[1:4])
    if os.geteuid() != 0 or uid <= 0 or gid <= 0:
        raise SystemExit('Invalid runtime identity')
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
    resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        raise SystemExit('Unable to drop runtime capabilities')
    environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    os.execve(sys.argv[4], sys.argv[4:], environment)


if __name__ == '__main__':
    main()
