<?php
/** Keep extension-owned database links separate from the Plesk panel. */
class Modules_Tabularis_ContentInclude extends pm_Hook_ContentInclude
{
    public function getHeadContent()
    {
        $script = htmlspecialchars(pm_Context::getBaseUrl() . 'scripts/database-links.js', ENT_QUOTES, 'UTF-8');
        return '<script defer src="' . $script . '"></script>';
    }
}
