<?php
// Normal broker shutdown revokes temporary users. Keep configuration and failed-cleanup journals.
if (file_exists('/etc/tabularis-plesk/config.json')) {
    pm_ApiCli::callSbin('tabularis-service', ['uninstall']);
}
