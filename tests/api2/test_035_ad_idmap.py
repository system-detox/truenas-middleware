#!/usr/bin/env python3

# Author: Eric Turgeon
# License: BSD
# Location for tests into REST API of FreeNAS

import pytest
import sys
import os
import json
apifolder = os.getcwd()
sys.path.append(apifolder)
from functions import PUT, POST, GET, DELETE, SSH_TEST, wait_on_job
from auto_config import ip, hostname, password, user
from base64 import b64decode
from middlewared.test.integration.assets.directory_service import active_directory
from middlewared.test.integration.utils import call
from pytest_dependency import depends
from time import sleep

try:
    from config import AD_DOMAIN, ADPASSWORD, ADUSERNAME, ADNameServer, AD_COMPUTER_OU
    from config import (
        LDAPBASEDN,
        LDAPBINDDN,
        LDAPBINDPASSWORD,
        LDAPHOSTNAME
    )
    pytestmark = pytest.mark.ds
except ImportError:
    Reason = 'ADNameServer AD_DOMAIN, ADPASSWORD, or/and ADUSERNAME are missing in config.py"'
    pytestmark = pytest.mark.skip(reason=Reason)

BACKENDS = [
    "AD",
    "AUTORID",
    "LDAP",
    "NSS",
    "RFC2307",
    "TDB",
    "RID",
]

BACKEND_OPTIONS = None
WORKGROUP = None
nameserver1 = None
nameserver2 = None

job_id = None
dom_id = None


@pytest.fixture(scope="module")
def do_ad_connection(request):
    with active_directory(
        AD_DOMAIN,
        ADUSERNAME,
        ADPASSWORD,
        netbiosname=hostname,
        createcomputer=AD_COMPUTER_OU,
    ) as ad:
        yield (request, ad)


@pytest.mark.dependency(name="AD_IS_HEALTHY")
def test_03_enabling_activedirectory(do_ad_connection):
    results = GET('/activedirectory/started/')
    assert results.status_code == 200, results.text


def test_04_name_sid_resolution(request):
    depends(request, ["AD_IS_HEALTHY"])

    # get list of AD group gids for user from NSS
    ad_acct = call('user.get_user_obj', {'username': f'{ADUSERNAME}@{AD_DOMAIN}', 'get_groups': True})
    groups = set(ad_acct['grouplist'])

    # convert list of gids into sids
    sids = call('idmap.convert_unixids', [{'id_type': 'GROUP', 'id': x} for x in groups])
    sidlist = set([x['sid'] for x in sids['mapped'].values()])
    assert len(groups) == len(sidlist)

    # convert sids back into unixids
    unixids = call('idmap.convert_sids', list(sidlist))
    assert set([x['id'] for x in unixids['mapped'].values()]) == groups


@pytest.mark.dependency(name="GATHERED_BACKEND_OPTIONS")
def test_07_get_idmap_backend_options(request):
    """
    Create large set of SMB shares for testing registry.
    """
    depends(request, ["AD_IS_HEALTHY"])
    global BACKEND_OPTIONS
    global WORKGROUP
    results = GET("/idmap/backend_options")
    assert results.status_code == 200, results.text
    BACKEND_OPTIONS = results.json()

    results = GET("/smb")
    assert results.status_code == 200, results.text
    WORKGROUP = results.json()['workgroup']


@pytest.mark.parametrize('backend', BACKENDS)
def test_08_test_backend_options(request, backend):
    """
    Tests for backend options are performend against
    the backend for the domain we're joined to
    (DS_TYPE_ACTIVEDIRECTORY) so that auto-detection
    works correctly. The three default idmap backends
    DS_TYPE_ACTIVEDIRECTORY, DS_TYPE_LDAP,
    DS_TYPE_DEFAULT_DOMAIN have hard-coded ids and
    so we don't need to look them up.
    """
    depends(request, ["GATHERED_BACKEND_OPTIONS"], scope="session")
    opts = BACKEND_OPTIONS[backend]['parameters'].copy()
    set_secret = False

    payload = {
        "name": "DS_TYPE_ACTIVEDIRECTORY",
        "range_low": "1000000001",
        "range_high": "2000000000",
        "idmap_backend": backend,
        "options": {}
    }
    payload3 = {"options": {}}
    for k, v in opts.items():
        """
        Populate garbage data where an opt is required.
        This should get us past the first step of
        switching to the backend before doing more
        comprehensive tests.
        """
        if v['required']:
            payload["options"].update({k: "canary"})

    if backend == 'RFC2307':
        payload['options'].update({"ldap_server": "STANDALONE"})

    if not payload['options']:
        payload.pop('options')

    sleep(5)
    results = PUT("/idmap/id/1/", payload)
    assert results.status_code == 200, f'payload: {payload}, results: {results.text}'

    if backend == "AUTORID":
        IDMAP_CFG = "idmap config * "
    else:
        IDMAP_CFG = f"idmap config {WORKGROUP} "

    """
    Validate that backend was correctly set in smb.conf.
    """
    cmd = f'midclt call smb.getparm "{IDMAP_CFG}: backend" GLOBAL'
    results = SSH_TEST(cmd, user, password, ip)
    assert results['result'] is True, results['output']
    running_backend = results['stdout'].strip()
    assert running_backend == backend.lower(), results['output']

    if backend == "RID":
        """
        sssd_compat generates a lower range based
        on murmur3 hash of domain SID. Since we're validating
        basic functionilty, checking that our range_low
        changed is sufficient for now.
        """
        payload2 = {"options": {"sssd_compat": True}}
        results = PUT("/idmap/id/1/", payload2)
        assert results.status_code == 200, results.text
        out = results.json()
        assert out['range_low'] != payload['range_low']

    elif backend == "AUTORID":
        """
        autorid is unique among the idmap backends because
        its configuration replaces the default idmap backend
        "idmap config *".
        """
        payload3["options"] = {
            "rangesize": 200000,
            "readonly": True,
            "ignore_builtin": True,
        }
        results = PUT("/idmap/id/1/", payload3)
        assert results.status_code == 200, results.text

    elif backend == "AD":
        payload3["options"] = {
            "schema_mode": "SFU",
            "unix_primary_group": True,
            "unix_nss_info": True,
        }
        results = PUT("/idmap/id/1/", payload3)
        assert results.status_code == 200, results.text

    elif backend == "LDAP":
        payload3["options"] = {
            "ldap_base_dn": LDAPBASEDN,
            "ldap_user_dn": LDAPBINDDN,
            "ldap_url": LDAPHOSTNAME,
            "ldap_user_dn_password": LDAPBINDPASSWORD,
            "ssl": "ON",
            "readonly": True,
        }
        results = PUT("/idmap/id/1/", payload3)
        assert results.status_code == 200, results.text
        secret = payload3["options"].pop("ldap_user_dn_password")
        set_secret = True

    elif backend == "RFC2307":
        payload3["options"] = {
            "ldap_server": "STANDALONE",
            "bind_path_user": LDAPBASEDN,
            "bind_path_group": LDAPBASEDN,
            "user_cn": True,
            "ldap_domain": "",
            "ldap_url": LDAPHOSTNAME,
            "ldap_user_dn": LDAPBINDDN,
            "ldap_user_dn_password": LDAPBINDPASSWORD,
            "ssl": "ON",
            "ldap_realm": True,
        }
        results = PUT("/idmap/id/1/", payload3)
        assert results.status_code == 200, results.text
        r = payload3["options"].pop("ldap_realm")
        payload3["options"]["realm"] = r
        secret = payload3["options"].pop("ldap_user_dn_password")
        set_secret = True

    for k, v in payload3['options'].items():
        """
        At this point we should have added every supported option
        for the current backend. Iterate through each option and verify
        that it was written to samba's running configuration.
        """
        if k in ['realm', 'ssl']:
            continue

        cmd = f'midclt call smb.getparm "{IDMAP_CFG}: {k}" GLOBAL'
        results = SSH_TEST(cmd, user, password, ip)
        assert results['result'] is True, results['output']
        if k == 'ldap_url':
            v = f'ldaps://{v}'
        elif k == 'ldap_domain':
            v = None

        if v == 'STANDALONE':
            v = 'stand-alone'

        try:
            res = json.loads(results['stdout'].strip())
            assert res == v, f"{backend} - [{k}]: {res}"
        except json.decoder.JSONDecodeError:
            res = results['stdout'].strip()
            if isinstance(v, bool):
                v = str(v)

            assert v.casefold() == res.casefold(), f"{backend} - [{k}]: {res}"

    if set_secret:
        """
        API calls that set an idmap secret should result in the
        secret being written to secrets.tdb in Samba's private
        directory. To check this, force a secrets db dump, check
        for keys, then decode secret.
        """
        cmd = 'midclt call directoryservices.get_db_secrets'
        results = SSH_TEST(cmd, user, password, ip)
        assert results['result'] is True, results['output']
        sec = json.loads(results['stdout'].strip())
        sec_key = f"SECRETS/GENERIC/IDMAP_LDAP_{WORKGROUP}/{secret}"
        assert sec_key in sec[f'{hostname.upper()}$'], results['output']
        if sec_key in sec[f'{hostname.upper()}$']:
            stored_sec = sec[f'{hostname.upper()}$'][sec_key]
            decoded_sec = b64decode(stored_sec).rstrip(b'\x00').decode()
            assert secret == decoded_sec, stored_sec

    # reset idmap backend to RID to ensure that winbindd is running
    payload = {
        "name": "DS_TYPE_ACTIVEDIRECTORY",
        "range_low": "1000000001",
        "range_high": "2000000000",
        "idmap_backend": 'RID',
        "options": {}
    }
    sleep(5)
    results = PUT("/idmap/id/1/", payload)
    assert results.status_code == 200, results.text


def test_09_clear_idmap_cache(request):
    depends(request, ["AD_IS_HEALTHY"])
    results = GET("/idmap/clear_idmap_cache")
    assert results.status_code == 200, results.text
    job_id = results.json()
    job_status = wait_on_job(job_id, 180)
    assert job_status['state'] == 'SUCCESS', str(job_status['results'])


def test_10_idmap_overlap_fail(request):
    """
    It should not be possible to set an idmap range for a new
    domain that overlaps an existing one.
    """
    depends(request, ["AD_IS_HEALTHY"])
    payload = {
        "name": "canary",
        "range_low": "20000",
        "range_high": "2000000000",
        "idmap_backend": "RID",
        "options": {}
    }
    results = POST("/idmap/", payload)
    assert results.status_code == 422, results.text


def test_11_idmap_default_domain_name_change_fail(request):
    """
    It should not be possible to change the name of a
    default idmap domain.
    """
    depends(request, ["AD_IS_HEALTHY"])
    payload = {
        "name": "canary",
        "range_low": "1000000000",
        "range_high": "2000000000",
        "idmap_backend": "RID",
        "options": {}
    }
    results = PUT("/idmap/id/1", payload)
    assert results.status_code == 422, results.text


def test_12_idmap_low_high_range_inversion_fail(request):
    """
    It should not be possible to set an idmap low range
    that is greater than its high range.
    """
    depends(request, ["AD_IS_HEALTHY"])
    payload = {
        "name": "canary",
        "range_low": "2000000000",
        "range_high": "1900000000",
        "idmap_backend": "RID",
    }
    results = POST("/idmap/", payload)
    assert results.status_code == 422, results.text


@pytest.mark.dependency(name="CREATED_NEW_DOMAIN")
def test_13_idmap_new_domain(request):
    depends(request, ["AD_IS_HEALTHY"], scope="session")
    global dom_id
    cmd = 'midclt call idmap.get_next_idmap_range'
    results = SSH_TEST(cmd, user, password, ip)
    assert results['result'] is True, results['output']
    low, high = json.loads(results['stdout'].strip())

    payload = {
        "name": "canary",
        "range_low": low,
        "range_high": high,
        "idmap_backend": "RID",
        "options": {},
    }
    results = POST("/idmap/", payload)
    assert results.status_code == 200, results.text
    dom_id = results.json()['id']


def test_14_idmap_new_domain_duplicate_fail(request):
    """
    It should not be possible to create a new domain that
    has a name conflict with an existing one.
    """
    depends(request, ["AD_IS_HEALTHY"], scope="session")
    cmd = 'midclt call idmap.get_next_idmap_range'
    results = SSH_TEST(cmd, user, password, ip)
    assert results['result'] is True, results['output']
    low, high = json.loads(results['stdout'].strip())

    payload = {
        "name": "canary",
        "range_low": low,
        "range_high": high,
        "idmap_backend": "RID",
    }
    results = POST("/idmap/", payload)
    assert results.status_code == 422, results.text


def test_15_idmap_new_domain_autorid_fail(request):
    """
    It should only be possible to set AUTORID on
    default domain.
    """
    depends(request, ["CREATED_NEW_DOMAIN"])
    payload = {
        "idmap_backend": "AUTORID",
    }
    results = PUT(f"/idmap/id/{dom_id}", payload)
    assert results.status_code == 422, f"[update: {dom_id}]: {results.text}"


def test_16_idmap_delete_new_domain(request):
    """
    It should only be possible to set AUTORID on
    default domain.
    """
    depends(request, ["CREATED_NEW_DOMAIN"])
    results = DELETE(f"/idmap/id/{dom_id}")
    assert results.status_code == 200, f"[delete: {dom_id}]: {results.text}"
