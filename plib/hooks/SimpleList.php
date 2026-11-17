<?php
/** Add a scoped action to Plesk's native database cards. */
class Modules_Tabularis_SimpleList extends pm_Hook_SimpleList
{
    public function isEnabled($controller, $action, $activeList)
    {
        return $controller === 'database' && $action === 'list';
    }

    public function getData($controller, $action, $activeList, $data)
    {
        if (!$this->isEnabled($controller, $action, $activeList)
            || !file_exists(pm_Context::getVarDir() . 'configured')) {
            return $data;
        }
        try {
            $allowed = array_column(Modules_Tabularis_Catalog::current()['databases'], null, 'id');
        } catch (Throwable $error) {
            return $data;
        }
        foreach ($data as &$row) {
            $id = (int) ($row['id'] ?? 0);
            if (!isset($allowed[$id]) || !isset($row['actions']) || !is_array($row['actions'])) {
                continue;
            }
            $row['actions'][] = [
                'id' => 'tabularis-open-' . $id,
                'name' => 'tabularis-open',
                'title' => 'Open in Tabularis',
                'hint' => 'Open this database in a new tab using your current Plesk permissions',
                'icon' => pm_Context::getBaseUrl() . 'images/tabularis.png',
                'href' => '/tabularis/open/' . $id,
                'newWindow' => true,
            ];
        }
        unset($row);
        return $data;
    }
}
