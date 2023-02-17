#!/usr/bin/env python3

import os, sh, libvirt, paramiko, time, click
from scp import SCPClient
from git import Repo
from sys import stderr
from enum import Enum
from io import StringIO
from itertools import islice


class KernelConfigs(Enum):
    DEFCONFIG = 'defconfig'
    DEBCONFIG = 'debconfig'


def check_prerequisites(*prerequisites):
    def decorator(function):
        def wrapper(*args, **kwargs):
            for prerequisite in prerequisites:
                sh.dpkg('-s', prerequisite)
            return function(*args, **kwargs)
        return wrapper
    return decorator


@click.command('clone')
@click.option('-u', '--url', help='an url to the git repository with a kernel', required=True)
@click.option('-v', '--version', help='version of the cloning kernel', required=True)
@click.option('-d', '--dir', default='.', show_default=True, \
              help='path to the directory where the kernel cloned')
@check_prerequisites('git')
def kernel_clone(url: str, version: str, dir: str = '.') -> Repo:
    tag = 'v' + version
    return Repo.clone_from(url, os.path.join(dir, f'linux-kernel-{tag}'), branch=tag)


def _kernel_patch(kernel: str, patches: str, reverse: bool=False):
    args = [ '-d', kernel, '-p1', '-F0' ]
    if reverse:
        args.append('-R')

    config = os.path.join(patches, '.config')
    targets = None
    if os.path.exists(config):
        with open(config) as file:
            targets = file.readlines()
    else:
        targets = os.listdir(patches)

    for target in targets:
        patch_or_dir = os.path.join(patches, target.strip())
        if os.path.isdir(patch_or_dir):
            _kernel_patch(kernel, patch_or_dir, reverse)
        else:
            if not patch_or_dir.endswith('.patch'):
                patch_or_dir += '.patch'
            with open(patch_or_dir) as patch:
                sh.patch(*args, _in=patch.read(), _out=stderr)


@click.command('patch')
@click.option('-k', '--kernel', help='a path to the kernel', required=True)
@click.option('--patches', help='path to the patches root', required=True)
@click.option('--reverse', is_flag=True, default=False, help='undo patches or apply')
def kernel_patch(kernel: str, patches: str, reverse: bool=False):
    _kernel_patch(kernel, patches, reverse)


def _kernel_version(kernel: str) -> str:
    with open(os.path.join(kernel, 'Makefile')) as k:
        head = list(islice(k, 4))[1:]
    return '.'.join(map(lambda line: line.split(' = ')[1].strip(), head))

@click.command('version')
@click.option('-k', '--kernel', 'kernel', help='a path to the kernel', required=True)
def kernel_version(kernel: str):
    click.echo(_kernel_version(kernel))


@click.command('make')
@click.option('-k', '--kernel', help='a path to the kernel', required=True)
@click.option('-c', '--config', type=click.Choice([KernelConfigs.DEFCONFIG.value, KernelConfigs.DEBCONFIG.value]), \
              default=KernelConfigs.DEFCONFIG, help='choose the build type, default or deb-package', required=True)
@click.option('--config-path', help='a path to the config for deb-package build')
@check_prerequisites('git', 'gcc', 'make', 'flex', 'bison', 'fakeroot', 'bc', 'dpkg-dev', 'rsync', 'libelf-dev', 'libssl-dev')
def kernel_make(kernel: str, config: KernelConfigs, config_path: str):
    sh.make('-C', kernel, 'clean', _out=stderr)
    if config == KernelConfigs.DEBCONFIG.value:
        sh.cp(config_path, os.path.join(kernel, '.config'))
        sh.make('-C', kernel, 'olddefconfig', _out=stderr)
        sh.make('-C', kernel, '-j', '8', 'bindeb-pkg', _out=stderr)
    else:
        sh.make('-C', kernel, 'defconfig', _out=stderr)
        sh.make('-C', kernel, '-j', '8', _out=stderr)


vm_prerequisites = [ 'qemu-system-x86', 'libvirt-clients', 'bridge-utils', 'libvirt-daemon-system', 'virtinst', 'libvirt-dev' ]


@check_prerequisites(*vm_prerequisites)
def vm_exists(vm_name: str = 'debian10', libvirt_connection_uri: str = 'qemu:///system') -> bool:
    vmlist = StringIO()
    sh.virsh('--connect', libvirt_connection_uri, 'list', '--all', '--name', _out=vmlist)
    return vmlist.getvalue().split('\n').count(vm_name) == 1


@click.command('vm-create')
@click.option('-i', '--img', help='a path to the VM\'s disk image', required=True)
@click.option('-u', '--uri', default='qemu:///system', help='libvirt connection uri', show_default=True)
@click.option('-n', '--name', default='debian10', help='VM\'s name', show_default=True)
@click.option('-c', '--vcpus', default=1, help='number of cores for the VM', show_default=True)
@click.option('-m', '--memory', default=2048, help='number of RAM in MBytes', show_default=True)
@click.option('-o', '--os-variant', default='debian10', help='os variant according to virt-install --os-variant list', show_default=True)
@check_prerequisites(*vm_prerequisites)
def vm_create(img: str, \
        uri: str = 'qemu:///system', \
        name: str = 'debian10', \
        vcpus: int = 1, memory: int = 2048, \
        os_variant: str = 'debian10'):

    _, ext = os.path.splitext(img)
    if vm_exists(name, uri):
        raise Exception(f'Virtual machine {name} already exists')

    if not os.path.exists(img):
        raise FileNotFoundError(img)
    sh.virt_install('--connect', uri, \
        f'--name={name}', \
        f'--vcpus={vcpus}', \
        f'--memory={memory}', \
        '--disk', \
        f'path={img},format={ext}', \
        f'--os-variant={os_variant}', \
        '--import',
        '--noautoconsole', \
        '--noreboot', _out=stderr)


def check_vm_absence(vm_callback):
    def wrapper(*args, **kwargs):
        vm = kwargs.get('name', 'debian10')
        uri = kwargs.get('uri', 'qemu:///system')
        if not vm_exists(vm, uri):
            raise Exception(f'Virtual machine {vm} not found')
        return vm_callback(*args, **kwargs)
    return wrapper


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_start(name: str = 'debian10', uri: str = 'qemu:///system'):
    sh.virsh('--connect', uri, 'start', name, _out=stderr)


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_shutdown(name: str = 'debian10', uri: str = 'qemu:///system'):
    sh.virsh('--connect', uri, 'shutdown', name, _out=stderr)


@click.command('vm-destroy')
@click.option('-n', '--name', default='debian10', help='VM\'s name', show_default=True)
@click.option('-u', '--uri', default='qemu:///system', help='libvirt connection uri', show_default=True)
@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_destroy(name: str = 'debian10', uri: str = 'qemu:///system'):
    sh.virsh('--connect', uri, 'undefine', name, \
        '--managed-save', \
        '--snapshots-metadata', \
        '--checkpoints-metadata', \
        '--nvram', \
        '--remove-all-storage', _out=stderr)


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_ip(name: str = 'debian10', hostname: str = 'debian', uri: str = 'qemu:///system', network: str = 'default') -> str:
    connection = libvirt.open(uri)
    vm_lease = list(filter(lambda lease: lease['hostname'] == hostname, connection.networkLookupByName(network).DHCPLeases()))
    if not any(vm_lease):
        raise Exception(f'can\'t obtain VM ip; please be sure that network {network} started and VM {name} launched')
    return vm_lease[0]['ipaddr']


@click.command('vm-test')
@click.option('-k', '--kernel', 'kernel', help='a path to the kernel', required=True)
@click.option('-d', '--debpkg', 'debpkg', help='a path to the directory with deb-packages of kernel image and headers', required=True)
@click.option('-n', '--name', 'name', default='debian10', help='VM\'s name', show_default=True)
@click.option('-h', '--hostname', 'hostname', default='debian', help='hostname of the VM', show_default=True)
@click.option('-l', '--login', 'login', default='root', help='ssh login', show_default=True)
@click.option('-p', '--password', 'password', default='debian', help='ssh password', show_default=True)
@click.option('-u', '--uri', 'uri', default='qemu:///system', help='libvirt connection uri', show_default=True)
@click.option('--network', 'network', default='default', help='the libvirt network group where the hostname exists', show_default=True)
@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_test(kernel: str, debpkg: str, name: str = 'debian10', \
        hostname: str = 'debian', login: str = 'root', password: str = 'debian',
        uri: str = 'qemu:///system', network: str = 'default'):
    version = _kernel_version(kernel)

    # obtain kernel installation packages
    if not os.path.exists(debpkg):
        raise FileNotFoundError(debpkg)

    files = os.listdir(debpkg)
    header = list(filter(lambda f: f.endswith('.deb') and f.startswith(f'linux-headers-{version}'), files))
    if not any(header):
        raise FileNotFoundError('no kernel headers')
    header = header[0]
    image = list(filter(lambda f: f.endswith('.deb') and f.startswith(f'linux-image-{version}_'), files))
    if not any(image):
        raise FileNotFoundError('no installation kernel image')
    image = image[0]

    print(f'Found images {image} and {header}')

    vm_start(name, uri)

    # 1. obtain vm ip address
    time.sleep(90) # waiting for the boot
    ip = vm_ip(name, hostname, uri, network)
    print(f'Obtained VM IP {ip}')

    # 2. upload deb packages to vm
    with paramiko.SSHClient() as ssh_client:
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        ssh_client.connect(hostname=ip, username=login, password=password)
        def progress(filename, size, sent):
            stderr.write("%s's progress: %.2f%%   \r" % (filename.decode('ascii'), float(sent)/float(size)*100))
        with SCPClient(ssh_client.get_transport(), progress=progress) as scp_client:
            root_path = '/root' if login == 'root' else f'/home/{login}'
            scp_client.put(os.path.join(debpkg, image), os.path.join(root_path, image))
            print()
            scp_client.put(os.path.join(debpkg, header), os.path.join(root_path, header))
        time.sleep(30) # waiting for flush
        print('\nUploaded kernel installation images')

    # 3. install deb packages inside vm
        _, sshout, ssherr = ssh_client.exec_command(f'dpkg -i {header} {image}')
        print(sshout.read().decode())
        print(ssherr.read().decode() or '')
    # 4. reboot vm
        _, sshout, ssherr = ssh_client.exec_command(f'reboot')
        print(sshout.read().decode())
        print(ssherr.read().decode() or '')
    time.sleep(90) # waiting for reboot

    # 5. collect logs
    with paramiko.SSHClient() as ssh_client:
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        ssh_client.connect(hostname=ip, username=login, password=password)
        _, sshout, ssherr = ssh_client.exec_command('dmesg -HTl emerg,alert,crit,err')
        errors = sshout.read().decode()
        print(errors)
        print(ssherr.read().decode() or '')

    if errors:
        boot_errors = len(list(filter(lambda line: line != '', errors.split("\n"))))
        print(f'WARN: there are {boot_errors} boot errors', file=stderr)
        return
    vm_shutdown(name, uri)


@click.group()
def cli():
    pass

cli.add_command(kernel_clone)
cli.add_command(kernel_patch)
cli.add_command(kernel_version)
cli.add_command(kernel_make)
cli.add_command(vm_create)
cli.add_command(vm_destroy)
cli.add_command(vm_test)
