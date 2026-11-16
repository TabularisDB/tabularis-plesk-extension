<?php
class IndexController extends pm_Controller_Action
{
    public function indexAction()
    {
        $this->view->pageTitle = 'Tabularis';
        $this->view->configured = file_exists(pm_Context::getVarDir() . 'configured');
        $this->view->databases = [];
        $this->view->catalogError = false;
        try {
            $this->view->databases = Modules_Tabularis_Catalog::current()['databases'];
        } catch (Throwable $error) {
            $this->view->catalogError = true;
        }
    }

    public function authorizeAction()
    {
        $this->_helper->viewRenderer->setNoRender(true);
        $this->_helper->layout->disableLayout();
        $this->getResponse()->setHeader('Content-Type', 'application/json', true);
        $this->getResponse()->setHeader('Cache-Control', 'no-store', true);
        try {
            $directory = pm_Context::getVarDir();
            $secret = trim((string) file_get_contents($directory . 'callback.key'));
            $provided = (string) $this->getRequest()->getHeader('X-Tabularis-Callback');
            if (strlen($secret) < 32 || !hash_equals($secret, $provided)) {
                throw new pm_Exception('Private callback required.');
            }
            $catalog = Modules_Tabularis_Catalog::current();
            if (!$catalog['databases']) {
                throw new pm_Exception('No database access.');
            }
            $session = session_id();
            if ($session === '') {
                throw new pm_Exception('A verifiable panel session is required.');
            }
            $key = trim((string) file_get_contents($directory . 'grant.key'));
            if (strlen($key) < 32) {
                throw new pm_Exception('The broker is not configured.');
            }
            $catalog['session'] = hash_hmac('sha256', $session, $key);
            $catalog['issued_at'] = time();
            $catalog['expires_at'] = time() + 10;
            $payload = base64_encode(json_encode($catalog, JSON_THROW_ON_ERROR));
            $this->getResponse()->setBody(json_encode([
                'payload' => $payload,
                'signature' => hash_hmac('sha256', $payload, $key),
            ], JSON_THROW_ON_ERROR));
        } catch (Throwable $error) {
            $this->getResponse()->setHttpResponseCode(403);
            $this->getResponse()->setBody('{"error":"Plesk authorization denied"}');
        }
    }
}
