<?php
class Modules_Tabularis_CustomButtons extends pm_Hook_CustomButtons
{
    public function getButtons()
    {
        return [[
            'place' => [self::PLACE_DOMAIN, self::PLACE_HOSTING_PANEL_NAVIGATION,
                self::PLACE_ADMIN_NAVIGATION, self::PLACE_RESELLER_NAVIGATION],
            'title' => 'Tabularis',
            'description' => 'Open your databases in Tabularis',
            'link' => pm_Context::getActionUrl('index', 'index'),
            'contextParams' => true,
        ]];
    }
}
