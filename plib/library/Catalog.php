<?php
/** Resolve the effective session before reading any database identifiers. */
class Modules_Tabularis_Catalog
{
    public static function current(): array
    {
        if (!pm_Session::isExist()) {
            throw new pm_Exception('A Plesk session is required.');
        }
        $client = pm_Session::getClient();
        $context = Session::get();
        // The documented pm_Client object identifies a subuser's owner. Plesk's
        // current user row is also required to avoid granting owner permissions.
        $user = $context->auth()->getUserRow();
        $identity = 'client:' . $client->getId();
        if ($user) {
            if (!$user->isActive()) {
                throw new pm_Exception('The effective user is inactive.');
            }
            $identity .= ':user:' . (string) $user->id;
        } elseif (!$client->isAdmin() && !$client->isReseller()) {
            throw new pm_Exception('The effective user could not be verified.');
        }
        $identity .= ':actor:' . (string) pm_Session::getImpersonatedClientId();
        $adapter = pm_Bootstrap::getDbAdapter();
        $rows = $adapter->fetchAll(
            'SELECT db.id, db.name, db.type, db.dom_id, db.db_server_id, '
            . 'ds.host, ds.port, d.name AS domain, d.cl_id, d.webspace_id, d.status, c.status AS client_status '
            . 'FROM data_bases db JOIN domains d ON d.id = db.dom_id '
            . 'JOIN clients c ON c.id = d.cl_id JOIN DatabaseServers ds ON ds.id = db.db_server_id '
            . "WHERE db.type IN ('mysql', 'postgresql') ORDER BY db.id"
        );
        $databases = [];
        foreach ($rows as $row) {
            $domainId = (int) $row['dom_id'];
            if ((int) $row['status'] !== 0 || (int) $row['client_status'] !== 0) {
                continue;
            }
            $webspaceId = (int) $row['webspace_id'] ?: $domainId;
            if ($user) {
                if (!$user->isAdmin() && (int) $user->ownerId !== (int) $row['cl_id']
                    && !($client->isReseller() && $client->hasAccessToDomain($domainId))) {
                    continue;
                }
                if ((int) $user->subscriptionDomainId !== 0
                    && (int) $user->subscriptionDomainId !== $webspaceId) {
                    continue;
                }
            } elseif (!$client->hasAccessToDomain($domainId)) {
                continue;
            }
            $domain = pm_Domain::getByDomainId($domainId);
            if (!$user && !$client->isAdmin() && !$client->hasCorePermission('databasesManagement', $domain)) {
                continue;
            }
            if ($user) {
                // This check handles role permissions and subscription restrictions,
                // including additional domains. Exceptions deny only this domain.
                try {
                    $context->subscription()->checkUserPermissionForSite('databasesManagement', $domainId);
                } catch (Throwable $denied) {
                    continue;
                }
            }
            $databases[] = [
                'id' => (int) $row['id'], 'name' => (string) $row['name'],
                'driver' => $row['type'] === 'postgresql' ? 'postgres' : 'mysql',
                'domain_id' => $domainId, 'server_id' => (int) $row['db_server_id'],
                'domain' => (string) $row['domain'], 'owner' => (string) $row['cl_id'],
                'host' => $row['host'] === 'localhost' ? '127.0.0.1' : (string) $row['host'],
                'port' => (int) $row['port'],
            ];
        }
        return ['identity' => $identity, 'databases' => $databases];
    }
}
