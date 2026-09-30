# Mini-ArkTS Compiler

《编译技术》课程实验：Mini-ArkTS（鸿蒙 ArkTS 子集）编译器的设计与实现。

Python 3.9+，零第三方依赖。

## 功能（对应实验一~四）

| 模块 | 功能 | 对应实验 |
|---|---|---|
| `lexer.py` | 词法分析：关键字/装饰器/标识符/字面量/运算符，行列定位报错 | 实验一 |
| `parser.py` | 递归下降语法分析 + 优先级爬升，支持组件装饰器、声明式 UI、lambda；AST 导出 JSON | 实验一 |
| `semantic.py` | 三级作用域符号表、严格类型检查（禁止 number↔string 隐式转换）、@State 作用域校验 | 实验二 |
| `ir_gen.py` | 三地址码 IR，SSA 版本化 + phi，@CrossDevice 标记 | 实验三 |
| `codegen.py` | Mock-C 代码生成（ark_* API），RPC Stub/Skeleton | 实验三 |
| `scheduler.py` | 分布式调度模拟（轮询 vs 最短队列优先） | 实验三 |
| `optimizer.py` | 常量折叠/传播 + 死代码消除（循环安全：回边检测） | 实验四 |
| `fuzzer.py` | 变异模糊测试（300 用例，0 崩溃） | 实验四 |

## 命令行用法

```bash
python arktsc.py <命令> <源文件>
# 命令: tokens / ast / check / ir / emit-c / opt-c
# 退出码: 0 成功 | 1 词法错误 | 2 语法错误 | 3 语义错误 | 4 用法错误
```

示例：

```bash
python arktsc.py check demo.arkts
python arktsc.py emit-c demo.arkts > demo.c
gcc demo.c -o demo && ./demo
```

## 黑盒测试（对应考核：自动化测试通过率）

```bash
python tests/run_tests.py        # 100 个用例（合法40/边界20/错误40）
python tests/run_tests.py -v     # 显示每个用例
python tests/run_tests.py --cc   # 额外对合法用例做 gcc 编译检查
```

当前通过率：**100/100 (100%)**。

推送后 GitHub Actions 会自动运行全部用例（`.github/workflows/ci.yml`），
通过率见 Actions 页面与 Step Summary。

## ArkTS 语法支持范围

- 声明：`let/const`、类型标注、类型推断
- 语句：`if/else`、`while`、`for`、`return`、块语句（分号遵循 ASI 可省略）
- 函数：定义、调用、多参数、返回类型
- 鸿蒙特性：`@Entry/@Component/@State/@CrossDevice` 装饰器、组件方法、
  `build()` 声明式 UI（Column/Row/Text/Button 及链式属性）、lambda 事件回调
- 运算符：算术/关系/逻辑/一元/自增自减，全支持

## 已知限制

- Mock-C 生成覆盖数值类程序（字符串以占位处理）
- GMP 等第三方库迁移依赖外部网络环境
- 实验六 `.dot` 导出需昇腾 NPU + CANN 环境（CPU 后端不产出 GE 图）
