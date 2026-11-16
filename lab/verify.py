#!/usr/bin/env python3
"""Exercise real engine grants and, optionally, real Plesk session authorization."""

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from provision import CONTAINER, STATE, assert_lab, credentials, execute, inside, plesk


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def protected_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output)
    path.chmod(0o600)


def helper(path, request):
    result = inside(["/usr/local/psa/admin/bin/php", path], input_text=json.dumps(request), label="Credential helper")
    value = json.loads(result.stdout)
    require(value.get("ok") is True, "Credential helper returned an error.")
    return value["result"]


def sql(driver, username, password, database, statement, *, expect_success=True):
    if driver == "postgresql":
        command = 'read -r PGPASSWORD; export PGPASSWORD; exec psql -X -A -t -h 127.0.0.1 -U "$1" -d "$2" -v ON_ERROR_STOP=1'
    else:
        command = 'read -r MYSQL_PWD; export MYSQL_PWD; exec mariadb -N -h 127.0.0.1 -u "$1" "$2"'
    result = inside(["sh", "-c", command, "sh", username, database], input_text=password + "\n" + statement, check=False)
    require((result.returncode == 0) == expect_success, f"Unexpected {driver} access result for {database}.")
    return result.stdout.strip()


def verify_engine(path, values, driver, database, owner, password_key):
    suffix = secrets.token_hex(5)
    account = "tab_" + secrets.token_hex(12)
    password = secrets.token_urlsafe(32) + "Aa9!"
    old_table, new_table, owned_table = (f"tabularis_verify_{kind}_{suffix}" for kind in ("old", "new", "owned"))
    metadata = inside(["plesk", "db", "-Ne", f"SELECT id FROM data_bases WHERE name='{database}'"]).stdout.strip()
    require(metadata.isdigit(), "Fixture database is missing; run provision.py first.")
    request = {"databaseId": int(metadata), "username": account}
    protected_json(STATE / f"verify-{driver}.json", {**request, "password": password})
    identity = "bigint GENERATED ALWAYS AS IDENTITY" if driver == "postgresql" else "bigint AUTO_INCREMENT PRIMARY KEY"
    create_old = f"CREATE TABLE {old_table}(id {identity}, value varchar(80)); INSERT INTO {old_table}(value) VALUES ('application data');"
    sql(driver, owner, values[password_key], database, create_old)
    provisioned = False
    try:
        result = helper(path, {"action": "provision", **request, "password": password})
        provisioned = True
        require(result["created"] is True, "The verification account unexpectedly existed.")
        count = sql(driver, account, password, database, "SELECT count(*) FROM customers;")
        require(int(count) >= 120, "Nontrivial sample data is missing.")
        sql(driver, account, password, database, f"SELECT * FROM {old_table}; INSERT INTO {old_table}(value) VALUES ('extension write'); UPDATE {old_table} SET value='updated' WHERE id=2;")
        sql(driver, owner, values[password_key], database, f"CREATE TABLE {new_table}(id {identity}, value varchar(80)); INSERT INTO {new_table}(value) VALUES ('future application data');")
        sql(driver, account, password, database, f"SELECT * FROM {new_table}; INSERT INTO {new_table}(value) VALUES ('future sequence works'); CREATE TABLE {owned_table}(value varchar(80)); INSERT INTO {owned_table} VALUES ('preserve on revoke');")
        other = "postgres" if driver == "postgresql" else "psa"
        sql(driver, account, password, other, "SELECT 1;", expect_success=False)
        repeated = helper(path, {"action": "provision", **request, "password": secrets.token_urlsafe(32) + "Aa9!"})
        require(repeated["created"] is False, "Repeated provisioning replaced the account.")
        sql(driver, account, password, database, f"SELECT count(*) FROM {old_table};")
        sql(driver, owner, values[password_key], database, f"SELECT count(*) FROM {old_table};")
        helper(path, {"action": "revoke", **request})
        provisioned = False
        sql(driver, account, password, database, "SELECT 1;", expect_success=False)
        if driver == "postgresql":
            retained = sql(driver, "postgres", values["postgres_admin"], database, f"SELECT count(*) FROM {owned_table};")
        else:
            retained = sql(driver, owner, values[password_key], database, f"SELECT count(*) FROM {owned_table};")
        require(retained == "1", "Revocation did not preserve a user-created table.")
        helper(path, {"action": "revoke", **request})
        print(f"PASS {driver}: existing/future objects, writes, identity sequences, repeat provisioning, other-database denial, revocation, retained data")
    finally:
        if provisioned:
            helper(path, {"action": "revoke", **request})
        cleanup = ";".join(f"DROP TABLE IF EXISTS {name}" for name in (old_table,new_table,owned_table)) + ";"
        if driver == "postgresql":
            sql(driver, "postgres", values["postgres_admin"], database, cleanup)
            sql(driver, "postgres", values["postgres_admin"], database, f'DROP ROLE IF EXISTS "tab_ret_{account[4:]}";')
        else:
            sql(driver, owner, values[password_key], database, cleanup)


def verify_postgres_cleanup(path, values):
    """A preserved SECURITY DEFINER function must never acquire admin authority."""
    suffix = secrets.token_hex(5)
    username = "tab_" + secrets.token_hex(12)
    password = secrets.token_urlsafe(32) + "Aa9!"
    database = "tabularis_shop_pg"
    database_id = int(inside(["plesk", "db", "-Ne", f"SELECT id FROM data_bases WHERE name='{database}'"]).stdout.strip())
    request = {"databaseId": database_id, "username": username}
    schema = "tabularis_verify_private_" + suffix
    function = "tabularis_verify_function_" + suffix
    retained = "tab_ret_" + username[4:]
    helper(path, {"action": "provision", **request, "password": password})
    try:
        # Created after provisioning in a new schema, so it has no extension ACL.
        sql("postgresql", "postgres", values["postgres_admin"], database,
            f"CREATE SCHEMA {schema}; REVOKE ALL ON SCHEMA {schema} FROM PUBLIC; "
            f"CREATE TABLE {schema}.protected_data(value text); INSERT INTO {schema}.protected_data VALUES ('synthetic canary');")
        sql("postgresql", username, password, database,
            f"CREATE FUNCTION public.{function}() RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog "
            f"AS $$ BEGIN RETURN (SELECT value FROM {schema}.protected_data LIMIT 1); END $$;")
        statement = f"SELECT public.{function}();"
        sql("postgresql", "shop_pg_owner", values["pg_owner"], database, statement, expect_success=False)
        helper(path, {"action": "revoke", **request})
        sql("postgresql", "shop_pg_owner", values["pg_owner"], database, statement, expect_success=False)
        actual = sql("postgresql", "postgres", values["postgres_admin"], database,
                     "SELECT r.rolname || ':' || r.rolcanlogin || ':' || r.rolsuper || ':' || r.rolinherit "
                     f"FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.proname='{function}';")
        require(actual == retained + ":false:false:false", "A retained function acquired privileged ownership.")
        print("PASS PostgreSQL cleanup: preserved SECURITY DEFINER function gains no administrator privileges")
    finally:
        helper(path, {"action": "revoke", **request})
        sql("postgresql", "postgres", values["postgres_admin"], database,
            f'DROP FUNCTION IF EXISTS public.{function}(); DROP SCHEMA IF EXISTS {schema} CASCADE; DROP ROLE IF EXISTS "{retained}";')


def verify_active_query_revocation(path, values, driver, database, owner, owner_key):
    username = "tab_" + secrets.token_hex(12)
    password = secrets.token_urlsafe(32) + "Aa9!"
    database_id = int(inside(["plesk", "db", "-Ne", f"SELECT id FROM data_bases WHERE name='{database}'"]).stdout.strip())
    request = {"databaseId": database_id, "username": username}
    helper(path, {"action": "provision", **request, "password": password})

    def start_query(user, secret, seconds):
        if driver == "postgresql":
            command = 'read -r PGPASSWORD; export PGPASSWORD; exec psql -X -A -t -h 127.0.0.1 -U "$1" -d "$2" -v ON_ERROR_STOP=1 -c "SELECT 1;" -c "SELECT pg_sleep($3);"'
        else:
            command = 'read -r MYSQL_PWD; export MYSQL_PWD; exec mariadb --unbuffered -N -h 127.0.0.1 -u "$1" "$2" -e "SELECT 1; SELECT SLEEP($3);"'
        process = subprocess.Popen(["docker", "exec", "-i", CONTAINER, "sh", "-c", command, "sh", user, database, str(seconds)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdin.write(secret + "\n")
        process.stdin.close()
        require(process.stdout.readline().strip() == "1", "The active-query fixture could not connect.")
        return process

    active = unrelated = None
    try:
        active = start_query(username, password, 15)
        unrelated = start_query(owner, values[owner_key], 1)
        started = time.monotonic()
        helper(path, {"action": "revoke", **request})
        active.wait(timeout=3)
        require(active.returncode != 0 and time.monotonic() - started < 3, "A revoked SQL query continued running.")
        unrelated.wait(timeout=3)
        require(unrelated.returncode == 0, "Revocation interrupted an unrelated application user.")
        print(f"PASS {driver}: active query cancelled immediately; application session unaffected")
    finally:
        helper(path, {"action": "revoke", **request})
        for process in (active, unrelated):
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=3)


def login(origin, username, password, label):
    cookies = http.cookiejar.CookieJar()
    loopback = urllib.parse.urlsplit(origin).hostname in ("127.0.0.1", "localhost", "::1")
    context = ssl._create_unverified_context() if loopback else ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(cookies))
    document = opener.open(origin + "/login.php").read().decode()
    token = re.search(r'name="forgery_protection_token"[^>]*content="([^"]+)"', document)
    require(token is not None, "The Plesk login page did not provide a CSRF token.")
    data = urllib.parse.urlencode({"login_name": username, "passwd": password, "locale_id": "default", "forgery_protection_token": token.group(1)}).encode()
    opener.open(origin + "/login_up.php", data=data).read()
    protected_json(STATE / f"{label}-cookies.json", {cookie.name: cookie.value for cookie in cookies})
    return opener


def panel_catalog(opener, origin, callback_key, grant_key):
    request = urllib.request.Request(origin + "/modules/tabularis/index.php/index/authorize", headers={"X-Tabularis-Callback": callback_key})
    try:
        response = opener.open(request)
        envelope = json.loads(response.read())
    except urllib.error.HTTPError as error:
        require(error.code == 403, "Unexpected authorization HTTP status.")
        return None
    expected = hmac.new(grant_key.encode(), envelope["payload"].encode(), hashlib.sha256).hexdigest()
    require(hmac.compare_digest(expected, envelope["signature"]), "The catalog grant signature is invalid.")
    return json.loads(base64.b64decode(envelope["payload"], validate=True))


def private_callback(origin, label, source_ip, callback_key, grant_key):
    """Send credentials over stdin, never in curl flags or process arguments."""
    cookies = json.loads((STATE / f"{label}-cookies.json").read_text())
    headers = {"Host": urllib.parse.urlsplit(origin).netloc,
               "Cookie": "; ".join(name + "=" + value for name, value in cookies.items()),
               "X-Tabularis-Callback": callback_key, "X-Tabularis-Client-IP": source_ip}
    code = """import http.client,json,socket,sys
class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect('/run/tabularis-auth.sock')
connection=UnixHTTP('localhost')
connection.request('GET','/authorize',headers=json.load(sys.stdin))
response=connection.getresponse()
print(json.dumps({'status':response.status,'body':response.read().decode()}))
"""
    response = json.loads(inside(["python3", "-c", code], input_text=json.dumps(headers)).stdout)
    if response["status"] != 200:
        return response["status"], None
    envelope = json.loads(response["body"])
    expected = hmac.new(grant_key.encode(), envelope["payload"].encode(), hashlib.sha256).hexdigest()
    require(hmac.compare_digest(expected, envelope["signature"]), "Private callback signature is invalid.")
    return 200, json.loads(base64.b64decode(envelope["payload"], validate=True))


def session_ip(label):
    # Look up only this protected test session's bound IP; never put its ID in argv.
    code = """require_once '/usr/local/psa/admin/plib/api-common/cu.php';
pm_Bootstrap::init();
$cookies=json_decode(stream_get_contents(STDIN),true,16,JSON_THROW_ON_ERROR);
$ip=pm_Bootstrap::getDbAdapter()->fetchOne('SELECT ip_address FROM sessions WHERE sess_id=?',[$cookies['PLESKSESSID']??'']);
echo json_encode(['ip'=>$ip]);
"""
    cookies = (STATE / f"{label}-cookies.json").read_text()
    result = json.loads(inside(["/usr/local/psa/admin/bin/php", "-r", code], input_text=cookies).stdout)
    require(bool(result.get("ip")), "The test session has no verifiable source IP.")
    return result["ip"]


def verify_panel(values, origin):
    url = urllib.parse.urlsplit(origin)
    require(url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.query and not url.fragment and url.path in ('','/'), "The panel origin must be an HTTPS origin without a path or credentials.")
    callback_key = inside(["cat", "/usr/local/psa/var/modules/tabularis/callback.key"]).stdout.strip()
    grant_key = inside(["cat", "/usr/local/psa/var/modules/tabularis/grant.key"]).stdout.strip()
    expected = {"tabularis_shop_pg", "tabularis_shop_mysql"}
    sessions = {}
    identities = set()
    for label, username, key, allowed in (
        ("admin", "admin", "admin", True), ("customer", "tabularis-lab", "customer", True),
        ("subuser", "dbuser@example.test", "subuser", True), ("denied", "nodbuser@example.test", "subuser", False),
    ):
        sessions[label] = login(origin, username, values[key], label)
        catalog = panel_catalog(sessions[label], origin, callback_key, grant_key)
        if allowed:
            require(catalog is not None and {row["name"] for row in catalog["databases"]} == expected, f"Wrong database catalog for {label}.")
            identities.add(catalog["identity"])
        else:
            require(catalog is None, "A subuser without database permission was authorized.")
    require(len(identities) == 3, "Administrator, customer and subuser identities were collapsed.")
    try:
        plesk(["role", "--update", "LabDatabaseUser", "-owner", "tabularis-lab", "-databasesManagement", "false"])
        require(panel_catalog(sessions["subuser"], origin, callback_key, grant_key) is None, "A revoked role retained access through an existing session.")
    finally:
        plesk(["role", "--update", "LabDatabaseUser", "-owner", "tabularis-lab", "-databasesManagement", "true"])
    require(panel_catalog(sessions["subuser"], origin, callback_key, grant_key) is not None, "Restored role did not recover access.")
    print("PASS panel: administrator/customer/subuser identities, denied role, immediate role revocation")
    for label, allowed in (("admin", True), ("customer", True), ("subuser", True), ("denied", False)):
        source_ip = session_ip(label)
        status, catalog = private_callback(origin, label, source_ip, callback_key, grant_key)
        require((status == 200) == allowed, f"Wrong private callback access for {label}.")
        if allowed:
            require({row["name"] for row in catalog["databases"]} == expected, "Private callback returned a different catalog.")
    try:
        status, _ = private_callback(origin, "customer", "203.0.113.19", callback_key, grant_key)
        require(status in (302, 303, 401, 403), "The private callback did not preserve Plesk session IP binding.")
    finally:
        # Plesk invalidates the session after an IP mismatch; leave a fresh test login.
        login(origin, "tabularis-lab", values["customer"], "customer")
    print("PASS private callback: signed catalogs, denied role, original client IP binding")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", default="/usr/local/psa/admin/plib/modules/tabularis/credentials.php", help="Installed credential-helper path inside the lab container")
    parser.add_argument("--with-panel", action="store_true", help="Also test a fully configured extension and its live Plesk sessions")
    parser.add_argument("--origin", default="https://127.0.0.1:18443")
    arguments = parser.parse_args()
    assert_lab()
    values = credentials()
    verify_engine(arguments.helper, values, "postgresql", "tabularis_shop_pg", "shop_pg_owner", "pg_owner")
    verify_engine(arguments.helper, values, "mysql", "tabularis_shop_mysql", "shop_mysql_owner", "mysql_owner")
    verify_postgres_cleanup(arguments.helper, values)
    verify_active_query_revocation(arguments.helper, values, "postgresql", "tabularis_shop_pg", "shop_pg_owner", "pg_owner")
    verify_active_query_revocation(arguments.helper, values, "mysql", "tabularis_shop_mysql", "shop_mysql_owner", "mysql_owner")
    if arguments.with_panel:
        verify_panel(values, arguments.origin)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
