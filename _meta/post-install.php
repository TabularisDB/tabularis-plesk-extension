<?php
// Runtime installation is explicit: never download or replace a binary during a panel upgrade.
$directory = pm_Context::getVarDir();
if (!is_dir($directory)) {
    mkdir($directory, 0700, true);
}
pm_Settings::set('packageVersion', '0.1.0');
