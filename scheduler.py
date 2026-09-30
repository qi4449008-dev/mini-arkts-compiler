# -*- coding: utf-8 -*-
"""Mini-ArkTS 分布式调度模拟 (实验三 · 分布式部分)
模拟鸿蒙"分布式软总线"多设备协同:
1. 设备节点: phone(1.0x) / tablet(0.7x) / watch(0.4x), 各自带算力系数。
2. 任务单元: 把 IR 函数按基本块切成任务, 代价 = 指令条数。
3. 策略对比: round_robin(轮询) vs least_loaded(最短队列优先)。
4. @CrossDevice 任务在非本机设备执行时, 计入软总线通信时延 0.5ms/次。
输出: 每设备任务数/负载/占比 + makespan + 策略对比结论。
"""
from __future__ import annotations

BUS_MS = 0.5    # 软总线单次通信时延(ms)


class Device:
    def __init__(self, name, speed):
        self.name = name
        self.speed = speed          # 算力系数: 1.0=本机基准

    def run_ms(self, cost):
        return cost / self.speed


class Task:
    def __init__(self, name, cost, cross=False):
        self.name = name
        self.cost = cost            # 代价 = 本机 ms
        self.cross = cross          # 是否跨设备任务


class Result:
    def __init__(self, strategy, devices):
        self.strategy = strategy
        self.loads = {d.name: 0.0 for d in devices}
        self.counts = {d.name: 0 for d in devices}
        self.bus_ms = 0.0

    @property
    def makespan(self):
        return max(self.loads.values())

    def text(self):
        lines = [f"策略={self.strategy}  软总线通信={self.bus_ms:.1f}ms"]
        for name, load in self.loads.items():
            pct = load / self.makespan * 100 if self.makespan else 0
            lines.append(f"  {name:<8} 任务{self.counts[name]:>2}  "
                         f"负载{load:7.2f}ms  {pct:5.1f}%")
        lines.append(f"  makespan={self.makespan:.2f}ms")
        return "\n".join(lines)


def split_tasks(func):
    """IR 函数 -> 基本块任务列表 (label/goto 切分)"""
    blocks, cur = [], []
    for ins in func.instrs:
        if ins.op == "label" and cur:
            blocks.append(cur)
            cur = []
        cur.append(ins)
        if ins.op in ("goto", "if_goto", "ret"):
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    real = [b for b in blocks if any(x.op != "label" for x in b)]
    return [Task(f"{func.name}#b{i}", float(len(b)), cross=func.cross_device)
            for i, b in enumerate(real)]


def build_tasks(funcs):
    """全部函数 -> 任务单元 (跳过 __main__)"""
    tasks = []
    for f in funcs:
        if f.name == "__main__":
            continue
        tasks.extend(split_tasks(f))
    return tasks


def schedule(tasks, devices, strategy):
    """strategy: round_robin | least_loaded"""
    res = Result(strategy, devices)
    rr = 0
    for t in tasks:
        if strategy == "round_robin":
            dev = devices[rr % len(devices)]
            rr += 1
        else:                                    # least_loaded
            dev = min(devices, key=lambda d: res.loads[d.name] / d.speed)
        res.loads[dev.name] += dev.run_ms(t.cost)
        res.counts[dev.name] += 1
        if t.cross and dev.name != devices[0].name:
            res.bus_ms += BUS_MS
    return res


DEVICES = [Device("phone", 1.0), Device("tablet", 0.7), Device("watch", 0.4)]


def run_sim(funcs):
    """对两种策略各跑一遍, 返回 (结果列表, 文本报告)"""
    tasks = build_tasks(funcs)
    results = [schedule(tasks, DEVICES, "round_robin"),
               schedule(tasks, DEVICES, "least_loaded")]
    lines = [f"任务单元数: {len(tasks)}", ""]
    for r in results:
        lines.append(r.text())
        lines.append("")
    a, b = results
    if b.makespan < a.makespan:
        gain = (a.makespan - b.makespan) / a.makespan * 100
        lines.append(f"结论: least_loaded 比 round_robin 快 {gain:.1f}% "
                     f"({a.makespan:.2f}ms -> {b.makespan:.2f}ms)")
    else:
        lines.append("结论: 两种策略 makespan 相当")
    return results, "\n".join(lines)


if __name__ == "__main__":
    from parser import parse
    from ir_gen import generate_ir

    demo = '''
    function small(a: number): number {
      return a + 1;
    }
    function med(a: number, b: number): number {
      let t: number = a * b;
      let u: number = t + a;
      return u - b;
    }
    function big(n: number): number {
      let s: number = 0;
      let i: number = 0;
      while (i < n) {
        s = s + i * 2;
        s = s - 1;
        i++;
      }
      return s;
    }
    function huge(n: number): number {
      let s: number = 0;
      let i: number = 0;
      let j: number = 0;
      while (i < n) {
        j = 0;
        while (j < n) {
          s = s + i * j;
          j++;
        }
        i++;
      }
      return s;
    }
    @CrossDevice
    function remoteCalc(a: number, b: number): number {
      return a * b + a;
    }
    let r1: number = small(1);
    let r2: number = med(3, 4);
    let r3: number = big(50);
    let r4: number = huge(20);
    let r5: number = remoteCalc(3, 4);
    print(r1);
    print(r2);
    print(r3);
    print(r4);
    print(r5);
    '''
    ast, le, pe = parse(demo)
    if pe:
        print("PARSE FAIL:", pe[0])
    else:
        funcs = generate_ir(ast)
        _, report = run_sim(funcs)
        print(report)
