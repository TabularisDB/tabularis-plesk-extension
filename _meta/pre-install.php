<?php
if (PHP_OS_FAMILY !== 'Linux' || PHP_VERSION_ID < 80100) {
    throw new pm_Exception('Tabularis requires Linux and Plesk PHP 8.1 or newer.');
}
if (!is_executable('/usr/bin/python3')) {
    throw new pm_Exception('Install Python 3.10 or newer before installing Tabularis.');
}
