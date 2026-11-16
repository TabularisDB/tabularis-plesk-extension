<?php
class IndexController extends pm_Controller_Action
{
    public function indexAction()
    {
        $this->view->pageTitle = 'Tabularis';
        $this->view->configured = file_exists(pm_Context::getVarDir() . 'configured');
    }
}
