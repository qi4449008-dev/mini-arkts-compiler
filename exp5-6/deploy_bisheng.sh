#!/bin/bash
# 实验五: 毕昇编译器部署与验证 (实际执行的命令序列)
# 环境: Windows 11 + WSL2 Ubuntu 24.04 (x86_64)
set -e

# ---- 1) WSL 平台与发行版 (官方 wsl --install 注册卡死, 改用 rootfs 导入) ----
wsl --install --no-distribution
curl -L -o ubuntu-2404-wsl.rootfs.tar.gz \
  https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz
wsl --import Ubuntu-2404 E:\WSL\Ubuntu ./ubuntu-2404-wsl.rootfs.tar.gz
wsl -d Ubuntu-2404 -- uname -m          # x86_64

# ---- 2) 依赖与工具链 ----
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential curl wget libatomic1

# ---- 3) 毕昇编译器下载与解压 ----
wget https://repo.huaweicloud.com/kunpeng/archive/compiler/bisheng_compiler/\
BiShengCompiler-4.0.0-x86-linux.tar.gz
sudo tar -zxf BiShengCompiler-4.0.0-x86-linux.tar.gz -C /opt
export PATH=/opt/BiShengCompiler-4.0.0-x86-linux/bin:$PATH
export LD_LIBRARY_PATH=/opt/BiShengCompiler-4.0.0-x86-linux/lib:$LD_LIBRARY_PATH

# ---- 4) 验证 ----
clang -v                                 # BiSheng Enterprise 4.0.0.B014
clang hello.c -o hello && ./hello        # Bisheng Compiler OK!
clang bench.c -O3 -march=native -o bench_bisheng
gcc   bench.c -O3 -march=native -o bench_gcc
./bench_gcc; ./bench_bisheng             # 12.4ms vs 13.2ms
strings bench_bisheng | grep -i bisheng  # 命中 B014 编译器标识
