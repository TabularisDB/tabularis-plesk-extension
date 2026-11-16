<?php
// Stop only extension-owned services. Database users and state are retained for explicit cleanup.
if (file_exists('/etc/tabularis-plesk/config.json')) {
    pm_ApiCli::callSbin('tabularis-service', ['uninstall']);
}
