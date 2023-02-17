#!/usr/bin/env python3
from .kernel_ci import cli


def main():
    cli()
    # 1. Obtaining kernel from kernel.org (git)
    # kernel_repo = kernel_clone('https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git', '5.10')
    # kernel_repo = Repo('./linux-kernel-v5.10')
    # kernel_root = kernel_repo.working_tree_dir

    # obtain kernel version
    # print(kernel_version(kernel_root))

    # 2. Applying provided patches
    # kernel_patch(kernel_root, '.tmp/patches')

    # 3. make with defconfig
    # kernel_make(kernel_root, KernelConfigs.DEFCONFIG)

    # 4. make with debconfig
    # kernel_make(kernel_root, KernelConfigs.DEBCONFIG, '.tmp/config')

    # 5. create virtual machine using QEMU (virt-install)
    # if not vm_exists():
    #     vm_create('./debian10.qcow2')

    # # 6. test kernel in QEMU
    # vm_test(kernel_root, '.')

    # 7. destroy virtual machine
    # if vm_exists():
    #     vm_destroy()


if __name__ == '__main__':
    main()