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

目标版本由 [scripts/truenas-targets.json](scripts/truenas-targets.json) 定义，每项包含官方 `.update` 地址、固定 SHA256、内核版本、构建容器和编译器。添加版本只需增加对应条目。自动运行处理所有目标；手动运行可通过 `version` 选择一个版本，或使用 `all`。

构建从校验通过的官方 `.update` 中提取内核 headers、生产配置和 `Module.symvers`，不重新编译整个内核。update 文件通过 GitHub Actions 缓存复用，缓存 key 包含目标版本和固定 SHA256，恢复后仍会校验。

每个目标的构建指纹包含该目标的 JSON 配置、[PKGBUILD](PKGBUILD)、[构建脚本](scripts/build-truenas-ko.sh)、[产物复用工具](scripts/truenas_artifacts.py) 和工作流内容，不包含整个目标清单或当前 Git 提交。因此只添加新版本不会使旧版本的指纹失效；修改驱动、共享构建逻辑或工作流会触发重新编译。

工作流查询已发布的 Release，查找相同指纹的 `.build.json` 记录，下载并校验完整产物后跳过该目标的下载和编译。没有记录、产物缺失或校验失败时重新编译；草稿 Release 不会被复用。旧 Release 没有指纹记录，需要首次重新编译。手动运行勾选 `force_rebuild` 可强制重编译所选目标，但仍可使用 update 下载缓存。

每次 Release 都包含所选目标的完整产物集合，包括本次编译和复用的产物。复用产物的构建信息保留原始编译提交。标签推送发布到同名 Release；分支和手动运行发布到独立 Release，名称为 `ci-<commit>-<run-id>-<attempt>`。所有运行均发布正式 Release：先创建草稿并上传全部附件，再公开发布并标记为 Latest；不会覆盖已存在的同名 Release。上传或发布失败可能留下草稿，重跑同一标签前需清理该草稿。手动选择单个版本时，Latest 也只包含该次所选版本的产物。

Actions 页面仍会为每个所选版本显示 `build` 矩阵任务，因为复用的文件也需要上传到本次 Release。这不表示每个版本都重新编译：复用成功时，`Cache official TrueNAS update` 和 `Build against official update headers` 步骤均显示 `skipped`。新 Release 中出现旧版本附件同样不代表重编译。

驱动版本、下载地址和 SHA256 从本仓库的 [PKGBUILD](PKGBUILD) 读取；编译选项与 [dkms.conf](dkms.conf) 一致：禁用 ASPM，启用 TX 多队列、PTP 和 RSS。

每个目标的 Release 附件包含 `.ko`、`.config`、`.txt`、`.SHA256SUMS` 和 `.build.json`。`.txt` 记录实际内核版本、原始构建提交、编译器、update 和 `Module.symvers` 校验和及模块 `vermagic`；`.build.json` 记录构建指纹和完整产物的 SHA256。工作流检查模块的 x86_64 架构、`vermagic` 内核版本和导入符号 CRC。

仓库需要启用 GitHub Actions，且仓库或组织策略允许工作流使用 `contents: write` 发布 Release；无需额外配置个人访问令牌。

### 加载前检查

在 TrueNAS 上执行 `uname -r`，确认与 Release 的 `.txt` 构建信息中 `Kernel release` 完全一致。版本标签相同或 `vermagic` 相同并不单独保证 ABI 兼容，仍需在目标 TrueNAS 系统验证实际加载和网卡工作情况。

产物没有签名；启用强制模块签名或 Secure Boot 策略的系统可能拒绝加载，需要使用系统信任的签名密钥处理。不要通过强制加载绕过版本或符号校验。替换当前正在使用的网卡驱动可能断开网络，请先准备本地控制台或带外管理。TrueNAS 升级可能更换内核或清理手动安装的模块，升级后需要重新匹配构建。
