import json
import os
import pytest
import sys

from pytest_dependency import depends
apifolder = os.getcwd()
sys.path.append(apifolder)
from functions import GET, POST, DELETE, SSH_TEST, wait_on_job
from auto_config import ha, artifacts, password, ip, pool_name
from middlewared.test.integration.utils import call, ssh

from middlewared.test.integration.assets.apps import chart_release
from middlewared.test.integration.assets.catalog import catalog
from middlewared.test.integration.assets.kubernetes import backup
from middlewared.test.integration.utils import file_exists_and_perms_check

pytestmark = pytest.mark.apps
backup_release_name = 'backupsyncthing'

# Read all the test below only on non-HA
if not ha:
    @pytest.mark.dependency(name='plex_version')
    def test_01_get_plex_version():
        global plex_version
        payload = {
            "item_name": "plex",
            "item_version_details": {
                "catalog": "TRUENAS",
                "train": 'charts'
            }
        }
        results = POST('/catalog/get_item_details/', payload)
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text
        plex_version = results.json()['latest_version']

    @pytest.mark.dependency(name='release_plex')
    def test_02_create_plex_chart_release(request):
        depends(request, ['setup_kubernetes', 'plex_version'], scope='session')
        global plex_id
        payload = {
            'catalog': 'TRUENAS',
            'item': 'plex',
            'release_name': 'myplex',
            'train': 'charts',
            'version': plex_version
        }
        results = POST('/chart/release/', payload)
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])
        plex_id = job_status['results']['result']['id']

    @pytest.mark.dependency(name='ix_app_backup')
    def test_03_create_kubernetes_backup_chart_releases_for_ix_applications(request):
        depends(request, ['release_plex'])
        global backup_name
        results = POST('/kubernetes/backup_chart_releases/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])
        backup_name = job_status['results']['result']

    @pytest.mark.dependency(name='check_datasets_to_ignore')
    def test_04_check_to_ignore_datasets_exist(request):
        datasets_to_ignore = set(call('kubernetes.to_ignore_datasets_on_backup', call('kubernetes.config')['dataset']))

        assert set(ds['id'] for ds in call(
            'zfs.dataset.query', [['OR', [['id', '=', directory] for directory in datasets_to_ignore]]]
        )) == datasets_to_ignore

    def test_05_backup_chart_release(request):
        depends(request, ['ix_app_backup', 'check_datasets_to_ignore'])
        datasets_to_ignore = set(call('kubernetes.to_ignore_datasets_on_backup', call('kubernetes.config')['dataset']))
        datasets = set(snap['dataset'] for snap in call('zfs.snapshot.query', [['id', 'rin', backup_name]]))

        assert datasets_to_ignore.intersection(datasets) == set()

    def test_06_get_ix_applications_kubernetes_backup(request):
        depends(request, ['ix_app_backup'])
        results = GET('/kubernetes/list_backups/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text
        assert backup_name in results.json(), results.text

    @pytest.mark.dependency(name='ix_app_backup_restored')
    def test_07_restore_ix_applications_kubernetes_backup(request):
        depends(request, ['ix_app_backup'])
        results = POST('/kubernetes/restore_backup/', backup_name)
        assert results.status_code == 200, results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_08_verify_plex_chart_release_still_exist(request):
        depends(request, ['release_plex', 'ix_app_backup_restored'])
        results = GET(f'/chart/release/id/{plex_id}/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text

    @pytest.mark.dependency(name='release_ipfs')
    def test_09_create_ipfs_chart_release(request):
        depends(request, ['setup_kubernetes'], scope='session')
        global ipfs_id
        payload = {
            'catalog': 'TRUENAS',
            'item': 'ipfs',
            'release_name': 'ipfs',
            'train': 'community'
        }
        results = POST('/chart/release/', payload)
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])
        ipfs_id = job_status['results']['result']['id']

    @pytest.mark.dependency(name='my_app_backup')
    def test_10_create_custom_name_kubernetes_chart_releases_backup(request):
        depends(request, ['release_plex', 'release_ipfs'])
        results = POST('/kubernetes/backup_chart_releases/', 'mybackup')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])


    def test_11_backup_snapshot_name_validation(request):
        depends(request, ['my_app_backup'])
        results = POST('/kubernetes/backup_chart_releases/', 'mybackup')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'FAILED'
        assert job_status['results']['error'] == "[EEXIST] 'ix-applications-backup-mybackup' snapshot already exists"

    def test_12_get_custom_name_kubernetes_backup(request):
        depends(request, ['my_app_backup'])
        results = GET('/kubernetes/list_backups/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text
        assert 'mybackup' in results.json(), results.text

    def test_13_restore_custom_name_kubernetes_backup(request):
        depends(request, ['my_app_backup'])
        results = POST('/kubernetes/restore_backup/', 'mybackup')
        assert results.status_code == 200, results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_14_verify_plex_and_ipfs_chart_release_still_exist(request):
        depends(request, ['my_app_backup'])
        results = GET(f'/chart/release/id/{plex_id}/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text
        results = GET(f'/chart/release/id/{ipfs_id}/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text

    @pytest.mark.dependency(name='my_second_backup')
    def test_15_create_mysecondbackup_kubernetes_chart_releases_backup(request):
        depends(request, ['release_plex', 'release_ipfs'])
        results = POST('/kubernetes/backup_chart_releases/', 'mysecondbackup')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_16_delete_ipfs_chart_release(request):
        depends(request, ['release_ipfs'])
        results = DELETE(f'/chart/release/id/{ipfs_id}/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_17_restore_custom_name_kubernetes_backup(request):
        depends(request, ['my_second_backup'])
        results = POST('/kubernetes/restore_backup/', 'mysecondbackup')
        assert results.status_code == 200, results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_18_verify_plex_chart_still_exist_and_ipfs_does_not_exist(request):
        depends(request, ['my_app_backup'])
        results = GET(f'/chart/release/id/{plex_id}/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), dict), results.text
        results = GET(f'/chart/release/id/{ipfs_id}/')
        assert results.status_code == 404, results.text
        assert isinstance(results.json(), dict), results.text

    def test_19_delete_mybackup_kubernetes_backup(request):
        depends(request, ['my_app_backup'])
        results = POST('/kubernetes/delete_backup/', 'mybackup')
        assert results.status_code == 200, results.text
        assert results.json() is None, results.text

    def test_20_delete_ix_applications_kubernetes_backup(request):
        depends(request, ['ix_app_backup', 'ix_app_backup_restored'])
        results = POST('/kubernetes/delete_backup/', backup_name)
        assert results.status_code == 200, results.text
        assert results.json() is None, results.text

    @pytest.mark.dependency(name='k8s_snapshot_regression')
    def test_21_recreate_mybackup_kubernetes_backup_for_snapshots_regression(request):
        depends(request, ['my_app_backup'])
        results = POST('/kubernetes/backup_chart_releases/', 'mybackup')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_22_delete_mybackup_kubernetes_backup(request):
        depends(request, ['k8s_snapshot_regression'])
        results = POST('/kubernetes/delete_backup/', 'mybackup')
        assert results.status_code == 200, results.text
        assert results.json() is None, results.text

    def test_23_delete_mysecondbackup_kubernetes_backup(request):
        depends(request, ['my_second_backup'])
        results = POST('/kubernetes/delete_backup/', 'mysecondbackup')
        assert results.status_code == 200, results.text
        assert results.json() is None, results.text

    def test_24_delete_plex_chart_release(request):
        depends(request, ['release_plex'])
        results = DELETE(f'/chart/release/id/{plex_id}/')
        assert results.status_code == 200, results.text
        assert isinstance(results.json(), int), results.text
        job_status = wait_on_job(results.json(), 300)
        assert job_status['state'] == 'SUCCESS', str(job_status['results'])

    def test_25_get_k3s_logs():
        results = SSH_TEST('journalctl --no-pager -u k3s', 'root', password, ip)
        ks3_logs = open(f'{artifacts}/k3s-scale.log', 'w')
        ks3_logs.writelines(results['output'])
        ks3_logs.close()

    def test_26_backup_structure():

        def read_file_content(file_path: str) -> str:
            return ssh(f'cat {file_path}')

        with chart_release({
            'catalog': 'TRUENAS',
            'item': 'syncthing',
            'release_name': backup_release_name,
            'train': 'charts',
        }, wait_until_active=True) as chart_release_info:
            with backup() as backup_name:
                app_info = call(
                    'chart.release.get_instance', chart_release_info['id'], {'extra': {'retrieve_resources': True}}
                )
                backup_path = os.path.join(
                    '/mnt', pool_name, 'ix-applications/backups', backup_name, app_info['id']
                )
                for f in ('namespace.yaml', 'workloads_replica_counts.json'):
                    test_path = os.path.join(backup_path, f)
                    assert file_exists_and_perms_check(test_path) is True, test_path

                secrets_data = call(
                    'k8s.secret.query', [
                        ['type', 'in', ['helm.sh/release.v1', 'Opaque']],
                        ['metadata.namespace', '=', app_info['namespace']]
                    ]
                )
                for secret in secrets_data:
                    secret_file_path = os.path.join(backup_path, 'secrets', secret['metadata']['name'])
                    assert file_exists_and_perms_check(secret_file_path) is True, secret_file_path
                    exported_secret = call('k8s.secret.export_to_yaml', secret['metadata']['name'])
                    assert read_file_content(secret_file_path) == exported_secret

                assert read_file_content(os.path.join(backup_path, 'namespace.yaml')) == call(
                    'k8s.namespace.export_to_yaml', app_info['namespace']
                )

                assert json.loads(read_file_content(
                    os.path.join(backup_path, 'workloads_replica_counts.json')
                )) == call('chart.release.get_replica_count_for_resources', app_info['resources'])
