<?php
declare(strict_types=1);

/** Root-only credential adapter. Read one JSON request from stdin; never echo passwords. */
function fail(string $message): never { throw new RuntimeException($message); }
function qi(string $identifier): string { return '"' . str_replace('"', '""', $identifier) . '"'; }

function runPlesk(array $arguments, ?string $password = null): void
{
    $environment = getenv();
    if ($password !== null) { $environment['PSA_PASSWORD'] = $password; }
    $pipes = [];
    $process = proc_open(array_merge(['/usr/sbin/plesk', 'bin'], $arguments), [0 => ['pipe','r'], 1 => ['pipe','w'], 2 => ['pipe','w']], $pipes, null, $environment);
    if (!is_resource($process)) { fail('Plesk command could not be started.'); }
    fclose($pipes[0]);
    stream_get_contents($pipes[1]); fclose($pipes[1]);
    stream_get_contents($pipes[2]); fclose($pipes[2]);
    if (proc_close($process) !== 0) { fail('Plesk database account operation failed.'); }
}

function inspectDatabase(int $databaseId, bool $allowInactive = false): array
{
    $adapter = pm_Bootstrap::getDbAdapter();
    $row = $adapter->fetchRow('SELECT b.id, b.name, b.type, b.dom_id, b.db_server_id, d.name AS domain_name, d.cl_id, d.webspace_id, d.status AS domain_status, ws.status AS subscription_status, c.status AS client_status, s.host, s.port FROM data_bases b JOIN domains d ON d.id=b.dom_id JOIN domains ws ON ws.id=IF(d.webspace_id=0,d.id,d.webspace_id) JOIN clients c ON c.id=d.cl_id JOIN DatabaseServers s ON s.id=b.db_server_id WHERE b.id=?', [$databaseId]);
    if (!$row || !in_array($row['type'], ['mysql','postgresql'], true)) { fail('Database does not exist or uses an unsupported driver.'); }
    if (!$allowInactive && ((int)$row['domain_status'] !== 0 || (int)$row['subscription_status'] !== 0 || (int)$row['client_status'] !== 0)) { fail('Database owner, domain or subscription is not active.'); }
    if (!preg_match('/^[A-Za-z0-9_][A-Za-z0-9_$-]{0,63}$/D', $row['name'])) { fail('Database name is unsupported by the guarded credential adapter.'); }
    if (!preg_match('/^[A-Za-z0-9.:-]+$/D', $row['host'])) { fail('Database host has an unsupported format.'); }
    return [
        'databaseId'=>(int)$row['id'], 'driver'=>$row['type'], 'host'=>$row['host'],
        'port'=>(int)$row['port'], 'database'=>$row['name'], 'domainId'=>(int)$row['dom_id'],
        'domain'=>$row['domain_name'], 'ownerId'=>(int)$row['cl_id'],
        'webspaceId'=>(int)$row['webspace_id'] ?: (int)$row['dom_id'], 'serverId'=>(int)$row['db_server_id'],
    ];
}

function postgresAdmin(array $database): PDO
{
    $server = Db_Table_Broker::get('DatabaseServers')->find($database['serverId'])->current();
    if (!$server || !$server->isLocal() || !in_array($database['host'], ['localhost','127.0.0.1','::1'], true)) {
        fail('Remote PostgreSQL requires an operator-installed database isolation adapter.');
    }
    $connection = new PDO('pgsql:host=127.0.0.1;port='.$database['port'].';dbname='.$database['database'], $server->admin_login, $server->getPassword(), [PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION]);
    if (!$connection->query("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")->fetchColumn()) {
        fail('The local PostgreSQL administrator must be able to manage role grants and the HBA guard.');
    }
    return $connection;
}

function mysqlAdmin(array $database): PDO
{
    $server=Db_Table_Broker::get('DatabaseServers')->find($database['serverId'])->current();
    if (!$server) { fail('The database server no longer exists.'); }
    // The local PSA server stores its admin secret outside DatabaseServers.
    $connection = $server->isUsedForPsaDb()
        ? pm_Bootstrap::getDbAdapter()->getConnection()
        : new PDO('mysql:host='.$database['host'].';port='.$database['port'].';charset=utf8mb4', $server->admin_login, $server->getPassword(), [PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION]);
    $privileges = [];
    foreach ($connection->query('SHOW GRANTS FOR CURRENT_USER')->fetchAll(PDO::FETCH_COLUMN) as $grant) {
        if (preg_match('/^GRANT (.+) ON \*\.\* TO /i', $grant, $match)) {
            $privileges = array_merge($privileges, array_map('trim', explode(',', strtoupper($match[1]))));
        }
    }
    if (!in_array('ALL PRIVILEGES', $privileges, true)
        && (!in_array('PROCESS', $privileges, true)
            || !array_intersect(['SUPER', 'CONNECTION_ADMIN', 'CONNECTION ADMIN'], $privileges))) {
        fail('The registered MySQL administrator needs explicit global PROCESS and connection termination privileges.');
    }
    return $connection;
}

function killMySqlSessions(PDO $connection, string $username): void
{
    $statement=$connection->prepare('SELECT ID FROM information_schema.PROCESSLIST WHERE USER=? AND ID<>CONNECTION_ID()');
    $statement->execute([$username]);
    foreach ($statement->fetchAll(PDO::FETCH_COLUMN) as $id) {
        if (!ctype_digit((string)$id)) { fail('The database returned an invalid connection ID.'); }
        try { $connection->exec('KILL CONNECTION '.(int)$id); }
        catch (PDOException $error) {
            // A concurrently closed connection is already revoked; all other failures matter.
            if (($error->errorInfo[1] ?? null)!==1094) { throw $error; }
        }
    }
}

/** Guard only this generated role. Preserve all unrelated rules and their order. */
function setPostgresGuard(PDO $connection, string $username, string $databaseName, bool $remove): void
{
    $path = $connection->query('SHOW hba_file')->fetchColumn();
    if (!is_string($path) || !str_starts_with($path, '/') || !is_file($path) || is_link($path)) {
        fail('A regular local PostgreSQL HBA file is required.');
    }
    $lock = fopen('/run/lock/tabularis-postgresql-hba.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) { fail('Unable to lock the PostgreSQL HBA guard.'); }
    try {
        $old = file_get_contents($path);
        $stat = stat($path);
        if ($old === false || $stat === false) { fail('Unable to read the PostgreSQL HBA file.'); }
        $begin = '# BEGIN TABULARIS '.$username;
        $end = '# END TABULARIS '.$username;
        $new = preg_replace('/^'.preg_quote($begin,'/').'\R.*?^'.preg_quote($end,'/').'\R?/ms', '', $old);
        if ($new === null) { fail('Unable to process the PostgreSQL HBA file.'); }
        if (!$remove) {
            $u = qi($username); $d = qi($databaseName);
            $block = "$begin\nlocal $d $u scram-sha-256\nlocal all $u reject\nhost $d $u 127.0.0.1/32 scram-sha-256\nhost $d $u ::1/128 scram-sha-256\nhost all $u 0.0.0.0/0 reject\nhost all $u ::/0 reject\n$end\n";
            $new = $block.$new;
        }
        if ($new === $old) { return; }
        $temporary = tempnam(dirname($path), '.tabularis-hba-');
        if ($temporary === false) { fail('Unable to prepare the PostgreSQL HBA update.'); }
        try {
            if (file_put_contents($temporary, $new) !== strlen($new) || !chmod($temporary, $stat['mode'] & 0777) || !chown($temporary, $stat['uid']) || !chgrp($temporary, $stat['gid']) || !rename($temporary, $path)) {
                fail('Unable to install the PostgreSQL HBA guard.');
            }
            $errors = (int)$connection->query('SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL')->fetchColumn();
            if ($errors !== 0 || !$connection->query('SELECT pg_reload_conf()')->fetchColumn()) {
                file_put_contents($path, $old);
                $connection->query('SELECT pg_reload_conf()');
                fail('PostgreSQL rejected the HBA guard; the original file was restored.');
            }
        } finally { if (is_file($temporary)) { unlink($temporary); } }
    } finally { flock($lock, LOCK_UN); fclose($lock); }
}

function grantPostgresObjects(PDO $connection, string $username, array $database): void
{
    $u = qi($username);
    $schemas = $connection->query("SELECT nspname FROM pg_namespace WHERE nspname <> 'information_schema' AND nspname NOT LIKE 'pg\\_%' ESCAPE '\\' ORDER BY nspname")->fetchAll(PDO::FETCH_COLUMN);
    $owners = $connection->query("SELECT DISTINCT pg_get_userbyid(owner_id) FROM (SELECT relowner AS owner_id FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' UNION SELECT nspowner FROM pg_namespace WHERE nspname <> 'information_schema' AND nspname NOT LIKE 'pg\\_%' ESCAPE '\\' UNION SELECT datdba FROM pg_database WHERE datname=current_database()) owners")->fetchAll(PDO::FETCH_COLUMN);
    // Include Plesk-managed application roles that have not created an object yet.
    $applicationUsers = pm_Bootstrap::getDbAdapter()->fetchCol(
        'SELECT login FROM db_users WHERE db_server_id=? AND (db_id=? OR (db_id=0 AND dom_id=?))',
        [$database['serverId'], $database['databaseId'], $database['domainId']]
    );
    $owners = array_unique(array_merge($owners, $applicationUsers));
    $connection->beginTransaction();
    try {
        foreach ($schemas as $schema) {
            $s = qi($schema);
            $connection->exec("GRANT USAGE, CREATE ON SCHEMA $s TO $u");
            $connection->exec("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA $s TO $u");
            $connection->exec("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA $s TO $u");
            foreach ($owners as $owner) {
                if ($owner === $username) { continue; }
                $o = qi($owner);
                $connection->exec("ALTER DEFAULT PRIVILEGES FOR ROLE $o IN SCHEMA $s GRANT ALL PRIVILEGES ON TABLES TO $u");
                $connection->exec("ALTER DEFAULT PRIVILEGES FOR ROLE $o IN SCHEMA $s GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $u");
            }
        }
        $connection->commit();
    } catch (Throwable $error) { $connection->rollBack(); throw $error; }
}

function validatePostgresRole(PDO $connection, string $username, array $database): void
{
    $check = $connection->prepare('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname=?');
    $check->execute([$username]);
    if ($check->fetchColumn()) { fail('Generated PostgreSQL role has unexpected global privileges.'); }
    $memberships = $connection->prepare('SELECT parent.rolname, parent.rolsuper OR parent.rolcreatedb OR parent.rolcreaterole OR parent.rolreplication OR parent.rolbypassrls AS elevated, m.admin_option, EXISTS(SELECT 1 FROM pg_auth_members nested WHERE nested.member=parent.oid) AS nested FROM pg_auth_members m JOIN pg_roles child ON child.oid=m.member JOIN pg_roles parent ON parent.oid=m.roleid WHERE child.rolname=?');
    $memberships->execute([$username]);
    foreach ($memberships->fetchAll(PDO::FETCH_ASSOC) as $membership) {
        if ($membership['rolname'] !== $database['database'] || $membership['elevated']
            || $membership['admin_option'] || $membership['nested']) {
            fail('Generated PostgreSQL role has unexpected role membership.');
        }
    }
}

function provision(array $database, string $username, string $password): array
{
    $adapter = pm_Bootstrap::getDbAdapter();
    $existing = $adapter->fetchRow('SELECT db_id, dom_id FROM db_users WHERE login=? AND db_server_id=?', [$username,$database['serverId']]);
    if ($existing && ((int)$existing['db_id'] !== $database['databaseId'] || (int)$existing['dom_id'] !== $database['domainId'])) {
        fail('Generated database username is already assigned to another database.');
    }
    $pg = $database['driver']==='postgresql' ? postgresAdmin($database) : null;
    if ($database['driver'] === 'mysql') { mysqlAdmin($database); }
    if ($pg) {
        $statement=$pg->prepare('SELECT oid FROM pg_roles WHERE rolname=?'); $statement->execute([$username]);
        if (!$existing && $statement->fetchColumn()) { fail('Generated PostgreSQL username already exists outside this adapter.'); }
        // Install the guard before making a new password login usable.
        setPostgresGuard($pg, $username, $database['database'], false);
    }
    $server = $database['host'].':'.$database['port'];
    if (!$existing) {
        runPlesk(['database','--create-dbuser',$username,'-passwd','','-domain',$database['domain'],'-server',$server,'-database',$database['database']], $password);
    }
    if ($pg) {
        try {
            validatePostgresRole($pg, $username, $database);
            grantPostgresObjects($pg,$username,$database);
            $pg->exec('ALTER ROLE '.qi($username).' LOGIN');
        } catch (Throwable $error) {
            $pg->exec('ALTER ROLE '.qi($username).' NOLOGIN');
            throw $error;
        }
    } elseif (in_array($database['host'], ['localhost','127.0.0.1','::1'], true)) {
        runPlesk(['database','--update-dbuser',$username,'-server',$server,'-set-acl','localhost,127.0.0.1,::1']);
    }
    return $database + ['username'=>$username, 'created'=>!$existing];
}

function revoke(array $database, string $username): array
{
    $adapter = pm_Bootstrap::getDbAdapter();
    $existing = $adapter->fetchRow('SELECT db_id, dom_id FROM db_users WHERE login=? AND db_server_id=?', [$username,$database['serverId']]);
    if ($existing && ((int)$existing['db_id'] !== $database['databaseId'] || (int)$existing['dom_id'] !== $database['domainId'])) {
        fail('Generated database username belongs to another database.');
    }
    $pg = $database['driver']==='postgresql' ? postgresAdmin($database) : null;
    $mysql = $database['driver']==='mysql' ? mysqlAdmin($database) : null;
    if ($pg) {
        $statement=$pg->prepare('SELECT oid FROM pg_roles WHERE rolname=?'); $statement->execute([$username]);
        if ($statement->fetchColumn()) {
            $u=qi($username);
            $pg->exec("ALTER ROLE $u NOLOGIN PASSWORD NULL");
            $statement=$pg->prepare('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename=? AND pid<>pg_backend_pid()'); $statement->execute([$username]);
            // Never transfer executable objects to postgres or an application owner:
            // a SECURITY DEFINER function would acquire that owner's privileges.
            $pg->beginTransaction();
            try {
                $owned=$pg->prepare("SELECT count(*) FROM pg_shdepend WHERE refclassid='pg_authid'::regclass AND refobjid=(SELECT oid FROM pg_roles WHERE rolname=?) AND deptype='o' AND dbid=(SELECT oid FROM pg_database WHERE datname=current_database())");
                $owned->execute([$username]);
                if ((int)$owned->fetchColumn() > 0) {
                    $retained='tab_ret_'.substr($username,4);
                    $r=qi($retained);
                    $marker='Tabularis retained objects for '.$username.' in Plesk database '.$database['databaseId'];
                    $role=$pg->prepare("SELECT oid, shobj_description(oid,'pg_authid') AS marker FROM pg_roles WHERE rolname=?");
                    $role->execute([$retained]);
                    $prior=$role->fetch(PDO::FETCH_ASSOC);
                    if ($prior && $prior['marker']!==$marker) { fail('Retained PostgreSQL owner name is already in use.'); }
                    if (!$prior) {
                        $pg->exec("CREATE ROLE $r NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0 PASSWORD NULL");
                        $pg->exec('COMMENT ON ROLE '.$r.' IS '.$pg->quote($marker));
                    }
                    // A retained owner must never inherit an existing account's authority.
                    $attributes=$pg->prepare("SELECT count(*) FROM pg_roles r WHERE r.rolname=? AND (r.rolcanlogin OR r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolinherit OR r.rolreplication OR r.rolbypassrls OR EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid OR m.roleid=r.oid))");
                    $attributes->execute([$retained]);
                    if ((int)$attributes->fetchColumn()!==0) { fail('Retained PostgreSQL owner has unexpected privileges.'); }
                    $pg->exec('REASSIGN OWNED BY '.$u.' TO '.$r);
                }
                // Owned objects were preserved above; this removes only the old role's ACLs.
                $pg->exec('DROP OWNED BY '.$u);
                $pg->commit();
            } catch (Throwable $error) { $pg->rollBack(); throw $error; }
        }
    }
    if ($existing) { runPlesk(['database','--remove-dbuser',$username,'-server',$database['host'].':'.$database['port']]); }
    // DROP USER does not terminate existing MySQL sessions. Remove credentials
    // first so no new connection can race the exact-username cancellation.
    if ($mysql) { killMySqlSessions($mysql,$username); }
    if ($pg) {
        // Plesk can leave a NOLOGIN role behind after removing its account record.
        $pg->exec('DROP ROLE IF EXISTS '.qi($username));
        setPostgresGuard($pg,$username,$database['database'],true);
    }
    return ['databaseId'=>$database['databaseId'],'username'=>$username,'revoked'=>true];
}

try {
    if (PHP_SAPI !== 'cli' || !function_exists('posix_geteuid') || posix_geteuid() !== 0) { fail('This adapter requires a root command-line process.'); }
    $raw=stream_get_contents(STDIN,16385);
    if (strlen($raw)>16384) { fail('Request is too large.'); }
    $request=json_decode($raw,true,16,JSON_THROW_ON_ERROR);
    if (!is_array($request) || !isset($request['databaseId']) || !is_int($request['databaseId']) || $request['databaseId']<1) { fail('A numeric databaseId is required.'); }
    require_once '/usr/local/psa/admin/plib/api-common/cu.php';
    pm_Bootstrap::init();
    $action=$request['action']??'';
    $database=inspectDatabase($request['databaseId'],$action==='revoke');
    if ($action==='inspect') { $result=$database; }
    else {
        $username=$request['username']??'';
        if (!is_string($username) || !preg_match('/^tab_[a-f0-9]{24}$/D',$username)) { fail('Invalid generated database username.'); }
        if ($action==='revoke') { $result=revoke($database,$username); }
        elseif ($action==='provision') {
            $password=$request['password']??'';
            if (!is_string($password) || strlen($password)<24 || strlen($password)>128 || str_contains($password,"\0") || str_contains($password,"\n") || str_contains($password,"\r")) { fail('Invalid generated database password.'); }
            $result=provision($database,$username,$password);
        } else { fail('Unsupported action.'); }
    }
    echo json_encode(['ok'=>true,'result'=>$result],JSON_THROW_ON_ERROR),"\n";
} catch (Throwable $error) {
    // Plesk/PDO errors can include private connection details. The broker receives no raw exception.
    $safe=$error instanceof RuntimeException && !$error instanceof PDOException ? $error->getMessage() : 'The credential adapter could not complete this operation.';
    fwrite(STDERR,json_encode(['ok'=>false,'error'=>$safe])."\n");
    exit(1);
}
