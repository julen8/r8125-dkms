## 这是什么

RealTek R8125B 网卡驱动的 DKMS 版本，启用 TX 多队列，启用 RSS，禁用 ASPM。

为和 [官方仓库中的包](https://packages.debian.org/sid/r8125-dkms) 保持一致，从 9.013.02-2 起，本人维护的包名和Github仓库名都从 `realtek-r8125-dkms` 更改为 `r8125-dkms`。更新时直接安装新的包，安装时在提示卸载旧包时确认即可。

事实上，由Debian官方维护的 `r8125-dkms` 已经进入 [`sid` 仓库](https://packages.debian.org/unstable/r8125-dkms)和 [`bookworm` 仓库](https://packages.debian.org/bookworm/r8125-dkms)的 `non-free` Component，由Proxmox维护的 `r8125-dkms` 也已经进入 PVE 8.x的 `pve-no-subscription` Component（见[这里](http://download.proxmox.com/debian/pve/dists/bookworm/pve-no-subscription/binary-amd64)的r8125-dkms）。版本虽然相对会老一些，但针对他们所维护的内核是适配的。也就是说，你如果不想追新，你可以直接在sources.list中启用 `bookworm/non-free`（针对Debian bookworm），或者 `bookworm/pve-no-subscription` （针对PVE 8），然后直接安装 `r8125-dkms` 。

```
$ apt policy r8125-dkms
r8125-dkms:
  Installed: 9.011.00-4.1
  Candidate: 9.011.00-4.1
  Version table:
 *** 9.011.00-4.1 500
        500 http://download.proxmox.com/debian/pve bookworm/pve-no-subscription amd64 Packages
     9.011.00-3 500
        500 https://deb.debian.org/debian bookworm/non-free amd64 Packages
```

## 适用对象

适用于 Debian 和基于 Debian 的发行版。

## 如何使用

需要先安装以下两个包：

- `dkms`

- 内核的`headers`文件，比如 Debian 是`linux-headers-amd64`这个包，Proxmox VE 是`proxmox-default-headers`这个包（8.0.3+），其他发行版类似。

提供一个 Proxmox VE 安装本驱动的教程：https://evine.win/p/pve-install-realtek-8125-driver/

## 如何自己编译

直接使用 [makedeb](https://docs.makedeb.org/) 来构建安装包，简单方便。先安装 [makedeb](https://docs.makedeb.org/)，然后在本仓库根目录下运行以下命令即可编译产生`r8125-dkms_<version>_all.deb`。

```shell
makedeb
```

注：现在RealTEK针对下载驱动启用了验证码验证，所以 [makedeb](https://docs.makedeb.org/) 无法自动下载RealTEK的驱动源码压缩包，这时，你需要自行前往 [官网](https://www.realtek.com/Download/List?cate_id=584) 将 `2.5G Ethernet LINUX driver r8125` 驱动手动下载到仓库根目录，然后再运行上述命令。

## 使用 GitHub Actions 编译 TrueNAS 模块

[构建工作流](.github/workflows/truenas-ko.yml) 会在分支提交、标签推送以及手动运行时编译 x86_64 的 `r8125.ko`，并上传到本仓库的 GitHub Release。它不是 Debian 安装包，也不需要在 TrueNAS 上安装 DKMS。

内核源码从 [truenas/linux](https://github.com/truenas/linux) 获取，选择规则如下：

- 推送 `TS-25.04.2` 等标签时，严格使用内核源码仓库的同名标签。
- 分支提交或手动运行时，如果当前提交有唯一的 `TS-*` 标签，使用该标签；没有则默认使用 `TS-25.04.1`。
- 当前提交有多个 `TS-*` 标签时，构建会报错，请选择具体标签手动运行。
- 推送非 `TS-*` 标签或内核仓库不存在对应标签时，构建失败，不会静默退回默认版本。

例如，将包含工作流的提交标记为目标 TrueNAS 版本后推送：

```shell
git tag TS-25.04.2
git push origin TS-25.04.2
```

标签构建发布到同名 Release。无标签构建发布到独立的预发布 Release，名称为 `ci-TS-25.04.1-<commit>-<run-id>-<attempt>`，不会创建或移动 `TS-25.04.1` 标签。重复运行标签构建会更新同名 Release 的附件。

构建使用 Debian Trixie 容器和 GCC 14，合并对应内核源码中的 `debian_amd64.config`、`truenas.config` 和 `tn-production.config`，保留生产内核配置和版本后缀。由于 TrueNAS 启用 `CONFIG_MODVERSIONS`，工作流会构建内核及内置模块以生成完整的 `Module.symvers`，而不是仅执行 `modules_prepare`。因此构建时间和磁盘消耗较大。

驱动版本、下载地址和 SHA256 从本仓库的 [PKGBUILD](PKGBUILD) 读取；编译选项与 [dkms.conf](dkms.conf) 一致：禁用 ASPM，启用 TX 多队列、PTP 和 RSS。

Release 附件包含 `.ko`、`kernel.config`、`build-info.txt` 和 `SHA256SUMS`。`build-info.txt` 记录实际内核版本、源码提交、编译器和模块 `vermagic`。工作流会检查模块的 x86_64 架构和 `vermagic` 内核版本。

仓库需要启用 GitHub Actions，且仓库或组织策略允许工作流使用 `contents: write` 发布 Release；无需额外配置个人访问令牌。

### 加载前检查

在 TrueNAS 上执行 `uname -r`，确认与 Release 的 `build-info.txt` 中 `Kernel release` 完全一致。版本标签相同或 `vermagic` 相同并不单独保证 ABI 兼容，仍需在目标 TrueNAS 系统验证实际加载和网卡工作情况。

产物没有签名；启用强制模块签名或 Secure Boot 策略的系统可能拒绝加载，需要使用系统信任的签名密钥处理。不要通过强制加载绕过版本或符号校验。替换当前正在使用的网卡驱动可能断开网络，请先准备本地控制台或带外管理。TrueNAS 升级可能更换内核或清理手动安装的模块，升级后需要重新匹配构建。
