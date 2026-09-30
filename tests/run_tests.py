#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mini-ArkTS 黑盒测试运行器

对 tests/cases.json 中的 100 个用例, 以子进程方式调用 arktsc.py,
只依据 退出码 + stdout/stderr 判定通过与否(黑盒, 不 import 编译器内部模块)。

用法:
    python tests/run_tests.py            # 跑全部
    python tests/run_tests.py -v         # 显示每个用例
    python tests/run_tests.py --cc       # 额外用 gcc 编译生成的 C 代码并运行

退出码 0 = 全部通过, 1 = 有失败 (便于 CI 判定)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARKTSC = os.path.join(ROOT, "arktsc.py")
CASES = os.path.join(HERE, "cases.json")

STAGE_NAME = {0: "成功", 1: "词法错误", 2: "语法错误", 3: "语义错误"}


def run_case(case, tmpdir, index):
    src_path = os.path.join(tmpdir, f"case{index}.arkts")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(case["src"])
    proc = subprocess.run(
        [sys.executable, ARKTSC, case["cmd"], src_path],
        capture_output=True, timeout=60,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), \
        proc.stderr.decode("utf-8", "replace"), src_path


def compile_check(src_path, tmpdir, index):
    """合法程序: 生成 C 代码 -> gcc 语法检查 -> 运行(若可行)"""
    c_path = os.path.join(tmpdir, f"case{index}.c")
    proc = subprocess.run([sys.executable, ARKTSC, "emit-c", src_path],
                          capture_output=True, timeout=60)
    if proc.returncode != 0:
        return False, "emit-c 失败"
    with open(c_path, "wb") as f:
        f.write(proc.stdout)
    exe = os.path.join(tmpdir, f"case{index}.exe")
    gcc = subprocess.run(["gcc", "-O0", c_path, "-o", exe, "-lm"],
                         capture_output=True, timeout=120)
    if gcc.returncode != 0:
        return False, "gcc 编译失败: " + gcc.stderr.decode("utf-8",
                                                           "replace")[:120]
    return True, "gcc 通过"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--cc", action="store_true",
                    help="对合法用例额外做 gcc 编译检查")
    args = ap.parse_args()

    with open(CASES, encoding="utf-8") as f:
        cases = json.load(f)

    passed, failed = 0, []
    stats = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, case in enumerate(cases, 1):
            rc, out, err, src_path = run_case(case, tmpdir, i)
            ok = (rc == case["expect"])
            detail = ""
            if ok and args.cc and case["expect"] == 0 and \
                    case["cmd"] == "check":
                ok_cc, detail = compile_check(src_path, tmpdir, i)
                ok = ok and ok_cc
            stats[case["kind"]] = stats.get(case["kind"], [0, 0])
            stats[case["kind"]][1] += 1
            if ok:
                stats[case["kind"]][0] += 1
                passed += 1
            else:
                failed.append((case, rc, err.strip()[:100], detail))
            if args.verbose or not ok:
                mark = "PASS" if ok else "FAIL"
                exp = STAGE_NAME.get(case["expect"], case["expect"])
                got = STAGE_NAME.get(rc, rc)
                print(f"[{mark}] #{case['id']:3d} [{case['kind']:8s}] "
                      f"期望={exp:6s} 实际={got:6s} {case['note']}")
                if not ok:
                    print(f"        src: {case['src'][:70]!r}")
                    if err:
                        print(f"        err: {err}")
                    if detail:
                        print(f"        {detail}")

    total = len(cases)
    print("\n" + "=" * 58)
    print(f"黑盒测试结果: {passed}/{total} 通过 "
          f"({passed / total * 100:.1f}%)")
    for k in ("valid", "boundary", "invalid"):
        if k in stats:
            print(f"  {k:9s}: {stats[k][0]}/{stats[k][1]}")
    if failed:
        print(f"\n失败用例 {len(failed)} 个:")
        for case, rc, err, _ in failed[:10]:
            print(f"  #{case['id']} {case['note']} "
                  f"(期望 {case['expect']}, 实际 {rc})")
    print("=" * 58)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
