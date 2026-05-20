import os

import pytest
import yaml

from mock import Mock, MagicMock, patch

from teuthology import provision


class TestDownburst(object):
    def setup_method(self):
        self.ctx = Mock()
        self.ctx.os_type = 'rhel'
        self.ctx.os_version = '7.0'
        self.ctx.config = dict()
        self.name = 'vpm999'
        self.status = dict(
            vm_host=dict(name='host999'),
            is_vm=True,
            machine_type='mtype',
            locked_by='user@a',
            description="desc",
        )

    def test_create_if_vm_success(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.executable = '/fake/path'
        dbrst.build_config = MagicMock(name='build_config')
        dbrst._run_create = MagicMock(name='_run_create')
        dbrst._run_create.return_value = (0, '', '')
        remove_config = MagicMock(name='remove_config')
        dbrst.remove_config = remove_config

        result = provision.create_if_vm(ctx, name, dbrst)
        assert result is True

        dbrst._run_create.assert_called_with()
        dbrst.build_config.assert_called_with()
        del dbrst
        remove_config.assert_called_with()

    def test_destroy_if_vm_success(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.destroy = MagicMock(name='destroy')
        dbrst.destroy.return_value = True

        result = provision.destroy_if_vm(name, user="user@a", _downburst=dbrst)
        assert result is True

        dbrst.destroy.assert_called_with()

    def test_destroy_if_vm_wrong_owner(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.destroy = MagicMock(name='destroy', side_effect=RuntimeError)

        result = provision.destroy_if_vm(name, user='user@b',
                                         _downburst=dbrst)
        assert result is False

    def test_destroy_if_vm_wrong_description(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.destroy = MagicMock(name='destroy')
        dbrst.destroy = MagicMock(name='destroy', side_effect=RuntimeError)

        result = provision.destroy_if_vm(name, description='desc_b',
                                         _downburst=dbrst)
        assert result is False

    @patch('teuthology.provision.downburst.downburst_executable')
    def test_create_fails_without_executable(self, m_exec):
        name = self.name
        ctx = self.ctx
        status = self.status
        m_exec.return_value = ''
        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        result = dbrst.create()
        assert result is False

    @patch('teuthology.provision.downburst.downburst_executable')
    def test_destroy_fails_without_executable(self, m_exec):
        name = self.name
        ctx = self.ctx
        status = self.status
        m_exec.return_value = ''
        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        result = dbrst.destroy()
        assert result is False


BASEOS_REPO = {
    'id': 'baseos',
    'name': 'BaseOS',
    'baseurl': 'http://mirror.example.com/BaseOS/$basearch/os/',
    'enabled': True,
    'gpgcheck': False,
}
APPSTREAM_REPO = {
    'id': 'appstream',
    'name': 'AppStream',
    'baseurl': 'http://mirror.example.com/AppStream/$basearch/os/',
}
MACHINE = {'type': 'vps', 'cpus': 2, 'disk': '40G', 'ram': '4G'}
# os_type and os_version of each distro that supports custom repos
OS_VERSIONS = [
    ('rocky', '10.2'),
    ('centos', '9.stream'),
]


class TestDownburstDistroRepos(object):
    """
    build_config() turns the downburst 'distro' site config into
    cloud-init 'yum_repos' and a runcmd that disables the image's
    default repos.
    """
    status = dict(
        vm_host=dict(name='host999'),
        mac_address='52:54:00:00:00:01',
        machine_type='vps',
    )

    def user_info(self, downburst_conf, os_type='rocky', os_version='9.8'):
        conf = Mock()
        conf.downburst = downburst_conf
        with patch('teuthology.provision.downburst.config', conf):
            dbrst = provision.downburst.Downburst(
                'vpm999', os_type, os_version, self.status)
            try:
                assert dbrst.build_config()
                with open(dbrst.user_path) as f:
                    text = f.read()
            finally:
                for path in (dbrst.config_path, dbrst.user_path):
                    if path and os.path.exists(path):
                        os.remove(path)
                dbrst.config_path = dbrst.user_path = None
        assert text.startswith('#cloud-config\n')
        return yaml.safe_load(text)

    @staticmethod
    def default_repos_disabled(info, os_type='rocky'):
        cmds = provision.downburst.get_disable_default_repos_cmds(os_type)
        assert cmds
        return all(cmd in info['runcmd'] for cmd in cmds)

    @pytest.mark.parametrize('downburst_conf', [
        {'machine': MACHINE},
        {'machine': MACHINE, 'distro': None},
        {'machine': MACHINE, 'distro': {}},
        {'machine': MACHINE, 'distro': {'ubuntu': {'repo': {}}}},
        {'machine': MACHINE, 'distro': {'rocky': None}},
        {'machine': MACHINE, 'distro': {'rocky-9.8': None}},
        {'machine': MACHINE, 'distro': {'rocky': {'repo': None}}},
        {'machine': MACHINE, 'distro': {'rocky': {'disable_default': True}}},
    ], ids=[
        'no-distro', 'distro-none', 'distro-empty', 'other-distro',
        'os-type-empty', 'os-version-empty', 'repo-none',
        'disable-default-without-repos',
    ])
    def test_no_repos(self, downburst_conf):
        info = self.user_info(downburst_conf)
        assert 'yum_repos' not in info
        assert not self.default_repos_disabled(info)

    @pytest.mark.parametrize('os_type, os_version', OS_VERSIONS)
    def test_os_type_repos(self, os_type, os_version):
        info = self.user_info({'machine': MACHINE, 'distro': {
            os_type: {'repo': {os_type: [BASEOS_REPO, APPSTREAM_REPO]}},
        }}, os_type=os_type, os_version=os_version)
        assert info['yum_repos'] == {
            'baseos': {
                'name': BASEOS_REPO['name'],
                'baseurl': BASEOS_REPO['baseurl'],
                'enabled': True,
                'gpgcheck': False,
            },
            'appstream': {
                'name': APPSTREAM_REPO['name'],
                'baseurl': APPSTREAM_REPO['baseurl'],
            },
        }
        # default repos are disabled unless asked otherwise
        assert self.default_repos_disabled(info, os_type)

    @pytest.mark.parametrize('os_type, os_version',
                             OS_VERSIONS + [('rocky', '10')])
    def test_os_version_repos(self, os_type, os_version):
        info = self.user_info({'machine': MACHINE, 'distro': {
            f'{os_type}-{os_version}': {'repo': {os_type: [BASEOS_REPO]}},
        }}, os_type=os_type, os_version=os_version)
        assert list(info['yum_repos']) == ['baseos']
        assert self.default_repos_disabled(info, os_type)

    @pytest.mark.parametrize('os_type, os_version', OS_VERSIONS)
    def test_os_version_does_not_match_other_version(self, os_type,
                                                     os_version):
        info = self.user_info({'machine': MACHINE, 'distro': {
            f'{os_type}-0': {'repo': {os_type: [BASEOS_REPO]}},
        }}, os_type=os_type, os_version=os_version)
        assert 'yum_repos' not in info

    @pytest.mark.parametrize('os_type, os_version', OS_VERSIONS)
    def test_os_type_and_version_repos_merge(self, os_type, os_version):
        info = self.user_info({'machine': MACHINE, 'distro': {
            os_type: {'repo': {'base': [BASEOS_REPO]}},
            f'{os_type}-{os_version}': {
                'repo': {'appstream': [APPSTREAM_REPO]}},
        }}, os_type=os_type, os_version=os_version)
        assert sorted(info['yum_repos']) == ['appstream', 'baseos']

    @pytest.mark.parametrize('os_type, os_version', OS_VERSIONS)
    def test_os_version_overrides_same_repo_key(self, os_type, os_version):
        info = self.user_info({'machine': MACHINE, 'distro': {
            os_type: {'repo': {os_type: [BASEOS_REPO]}},
            f'{os_type}-{os_version}': {'repo': {os_type: [APPSTREAM_REPO]}},
        }}, os_type=os_type, os_version=os_version)
        assert list(info['yum_repos']) == ['appstream']

    @pytest.mark.parametrize('os_type, os_version', OS_VERSIONS)
    @pytest.mark.parametrize(
            'os_type_entry, os_version_entry, disable_default_expected', [
        ({}, {}, True),
        ({'disable_default': False}, {}, False),
        ({}, {'disable_default': False}, False),
        ({'disable_default': False}, {'disable_default': True}, True),
    ], ids=['default', 'os-false', 'version-false', 'version-overrides-os'])
    def test_disable_default_repos(self, os_type, os_version, os_type_entry,
                                   os_version_entry, disable_default_expected):
        info = self.user_info({'machine': MACHINE, 'distro': {
            os_type: {'repo': {os_type: [BASEOS_REPO]}, **os_type_entry},
            f'{os_type}-{os_version}': os_version_entry,
        }}, os_type=os_type, os_version=os_version)
        assert (self.default_repos_disabled(info, os_type)
                is disable_default_expected)

    def test_repos_ignored_for_non_yum_distro(self):
        info = self.user_info({'machine': MACHINE, 'distro': {
            'ubuntu': {'repo': {'ubuntu': [BASEOS_REPO]}},
        }}, os_type='ubuntu', os_version='22.04')
        assert 'yum_repos' not in info
        assert not any('sed -i' in str(c) for c in info['runcmd'])

    def test_os_type_is_case_insensitive(self):
        info = self.user_info({'machine': MACHINE, 'distro': {
            'rocky-9.8': {'repo': {'rocky': [BASEOS_REPO]}},
        }}, os_type='Rocky')
        assert list(info['yum_repos']) == ['baseos']
