from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NativeDatabaseActionTests(unittest.TestCase):
    def test_native_actions_are_preserved_and_only_current_authorized_database_gets_link(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'configured').touch()
            script = r'''<?php
class pm_Hook_SimpleList {}
class pm_Context {
    public static function getVarDir() { return $GLOBALS['directory'] . '/'; }
    public static function getBaseUrl() { return '/modules/tabularis/'; }
}
class Modules_Tabularis_Catalog {
    public static $deny = false;
    public static function current() {
        if (self::$deny) throw new Exception('Authorization unavailable');
        return ['databases' => [['id' => 7]]];
    }
}
$directory = $argv[1];
require $argv[2];
$hook = new Modules_Tabularis_SimpleList();
$rows = [['id' => 7, 'actions' => [['name' => 'connectionInfo']]],
         ['id' => 8, 'actions' => [['name' => 'openWebAdmin']]]];
$result = $hook->getData('database', 'list', false, $rows);
if ($result[0]['actions'][0] !== $rows[0]['actions'][0]
    || count($result[0]['actions']) !== 2
    || $result[0]['actions'][1]['href'] !== '/tabularis/open/7'
    || $result[1] !== $rows[1]) exit(1);
if ($hook->getData('domain', 'list', false, $rows) !== $rows) exit(2);
Modules_Tabularis_Catalog::$deny = true;
if ($hook->getData('database', 'list', false, $rows) !== $rows) exit(3);
Modules_Tabularis_Catalog::$deny = false;
unlink($directory . '/configured');
if ($hook->getData('database', 'list', false, $rows) !== $rows) exit(4);
'''
            path = Path(directory, 'test.php')
            path.write_text(script)
            subprocess.run(['php', str(path), directory, str(ROOT / 'plib/hooks/SimpleList.php')],
                           check=True, capture_output=True, text=True)
