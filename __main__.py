#!/usr/bin/env python3
from git import Repo
import os
from sys import stderr
import sh
from enum import Enum
from io import StringIO
from itertools import islice


class KernelConfigs(Enum):
    DEFCONFIG = 0
    DEBCONFIG = 1


def check_prerequisites(*prerequisites):
    def decorator(function):
        def wrapper(*args, **kwargs):
            for prerequisite in prerequisites:
                sh.dpkg('-s', prerequisite)
            return function(*args, **kwargs)
        return wrapper
    return decorator


@check_prerequisites('git')
def kernel_clone(url: str, version: str, directory: str = '.') -> Repo:
    tag = 'v' + version
    return Repo.clone_from(url, os.path.join(directory, f'linux-kernel-{tag}'), branch=tag)


def kernel_patch(kernel_root: str, patches_root: str, reverse: bool=False):
    args = [ '-d', kernel_root, '-p1', '-F0' ]
    if reverse:
        args.append('-R')

    config = os.path.join(patches_root, '.config')
    targets = None
    if os.path.exists(config):
        with open(config) as file:
            targets = file.readlines()
    else:
        targets = os.listdir(patches_root)

    for target in targets:
        patch_or_dir = os.path.join(patches_root, target.strip())
        if os.path.isdir(patch_or_dir):
            kernel_patch(kernel_root, patch_or_dir, reverse)
        else:
            if not patch_or_dir.endswith('.patch'):
                patch_or_dir += '.patch'
            with open(patch_or_dir) as patch:
                sh.patch(*args, _in=patch.read(), _out=stderr)


def kernel_version(kernel_root: str) -> str:
    with open(os.path.join(kernel_root, 'Makefile')) as kernel:
        head = list(islice(kernel, 4))[1:]
    return '.'.join(map(lambda line: line.split(' = ')[1].strip(), head))


@check_prerequisites('git', 'gcc', 'make', 'flex', 'bison', 'fakeroot', 'bc', 'dpkg-dev', 'rsync', 'libelf-dev', 'libssl-dev')
def kernel_make(kernel_root: str, config: KernelConfigs, extra_config_path: str):
    sh.make('-C', kernel_root, 'clean', _out=stderr)
    if config == KernelConfigs.DEBCONFIG:
        sh.cp(extra_config_path, os.path.join(kernel_root, '.config'))
        sh.make('-C', kernel_root, 'olddefconfig', _out=stderr)
        sh.make('-C', kernel_root, '-j', '8', 'bindeb-pkg', _out=stderr)
    else:
        sh.make('-C', kernel_root, 'defconfig', _out=stderr)
        sh.make('-C', kernel_root, '-j', '8', _out=stderr)


vm_prerequisites = [ 'qemu-system-x86', 'libvirt-clients', 'bridge-utils', 'libvirt-daemon-system', 'virtinst' ]


@check_prerequisites(*vm_prerequisites)
def vm_exists(vm_name: str = 'debian10', libvirt_connection_uri: str = 'qemu:///system') -> bool:
    vmlist = StringIO()
    sh.virsh('--connect', libvirt_connection_uri, 'list', '--all', '--name', _out=vmlist)
    return vmlist.getvalue().split('\n').count(vm_name) == 1


@check_prerequisites(*vm_prerequisites)
def vm_create(img_path: str, \
        libvirt_connection_uri: str = 'qemu:///system', \
        vm_name: str = 'debian10', \
        vcpus: int = 1, memory: int = 2048, \
        os_variant: str = 'debian10'):

    _, ext = os.path.splitext(img_path)
    if vm_exists(vm_name, libvirt_connection_uri):
        raise Exception(f'Virtual machine {vm_name} already exists')

    if not os.path.exists(img_path):
        raise FileNotFoundError(img_path)
    sh.virt_install('--connect', libvirt_connection_uri, \
        f'--name={vm_name}', \
        f'--vcpus={vcpus}', \
        f'--memory={memory}', \
        '--disk', \
        f'path={img_path},format={ext}', \
        f'--os-variant={os_variant}', \
        '--import',
        '--noautoconsole', \
        '--noreboot', _out=stderr)


def check_vm_absence(vm_callback):
    def wrapper(*args, **kwargs):
        vm = kwargs.get('vm_name', 'debian10')
        uri = kwargs.get('libvirt_connection_uri', 'qemu:///system')
        if not vm_exists(vm, uri):
            raise Exception(f'Virtual machine {vm} not found')
        return vm_callback(*args, **kwargs)
    return wrapper


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_start(vm_name: str = 'debian10', libvirt_connection_uri: str = 'qemu:///system'):
    sh.virsh('--connect', libvirt_connection_uri, 'start', vm_name, _out=stderr)


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_shutdown(vm_name: str = 'debian10', libvirt_connection_uri: str = 'qemu:///system'):
    sh.virsh('--connect', libvirt_connection_uri, 'destroy', vm_name, _out=stderr)


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_destroy(vm_name: str = 'debian10', libvirt_connection_uri: str = 'qemu:///system'):
    sh.virsh('--connect', libvirt_connection_uri, 'undefine', vm_name, \
        '--managed-save', \
        '--snapshots-metadata', \
        '--checkpoints-metadata', \
        '--nvram', \
        '--remove-all-storage', _out=stderr)


@check_vm_absence
@check_prerequisites(*vm_prerequisites)
def vm_test(kernel_root: str, debpkgs_root: str, vm_name: str = 'debian10', libvirt_connection_uri: str = 'qemu:///system'):
    version = kernel_version(kernel_root)

    # obtain kernel installation packages
    if not os.path.exists(debpkgs_root):
        raise FileNotFoundError(debpkgs_root)

    files = os.listdir(debpkgs_root)
    header = list(filter(lambda f: f.endswith('.deb') and f.startswith(f'linux-headers-{version}'), files))
    if not any(header):
        raise FileNotFoundError('no kernel headers')
    header = header[0]
    image = list(filter(lambda f: f.endswith('.deb') and f.startswith(f'linux-image-{version}_'), files))
    if not any(image):
        raise FileNotFoundError('no installation kernel image')
    image = image[0]

    vm_start(vm_name, libvirt_connection_uri)

    # 1. upload deb packages to vm
    # 2. install deb packages inside vm
    # 3. reboot vm
    # 4. collect logs
    vm_shutdown(vm_name, libvirt_connection_uri)


def main():
    # 1. Obtaining kernel from kernel.org (git)
    # kernel_repo = kernel_clone('https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git', '5.10')
    kernel_repo = Repo('./linux-kernel-v5.10')
    kernel_root = kernel_repo.working_tree_dir

    # obtain kernel version
    # print(kernel_version(kernel_root))

    # 2. Applying provided patches
    # kernel_patch(kernel_root, '.tmp/patches')

    # 3. make with defconfig
    # kernel_make(kernel_root, KernelConfigs.DEFCONFIG)

    # 4. make with debconfig
    # kernel_make(kernel_root, KernelConfigs.DEBCONFIG, '.tmp/config')

    # 5. create virtual machine using QEMU (virt-install)
    if not vm_exists():
        vm_create('./debian10.qcow2')

    # 6. test kernel in QEMU
    vm_test(kernel_root, '.')

    # 7. destroy virtual machine
    if vm_exists():
        vm_destroy()


if __name__ == '__main__':
    main()