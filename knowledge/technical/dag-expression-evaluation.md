# DAG 依赖表达式求值：从已知节点计算全部变量

> 给定一组带依赖关系的变量节点，其中部分节点拥有初始值，其余节点通过 `+`、`-`、`*`、`/` 引用其他节点。目标是计算所有可求节点，并检测缺失引用、循环依赖和除零错误。

## 1. 示例输入

```js
const input = [
  { id: 'A', operator: '+', refs: ['B', 'C', 'D'] },
  { id: 'B', operator: '*', refs: ['C', 'D', 'E'] },
  { id: 'C', value: 10 },
  { id: 'D', operator: '-', refs: ['C', 'E'] },
  { id: 'E', operator: '/', refs: ['C', 'F'] },
  { id: 'F', value: 2 }
];
```

这里 `C = 10`、`F = 2` 是已知叶子节点，其他节点必须先计算其依赖项。

## 2. 依赖关系

```text
C = 10                 F = 2
│                       │
└──────────┬────────────┘
           ▼
      E = C / F = 5
           │
           ▼
      D = C - E = 5
           │
           ▼
 B = C × D × E = 250
           │
           ▼
 A = B + C + D = 265
```

更完整地看：

- `E` 依赖 `C、F`
- `D` 依赖 `C、E`
- `B` 依赖 `C、D、E`
- `A` 依赖 `B、C、D`

只要依赖图中没有环，就可以把它看成一个 **DAG（Directed Acyclic Graph，有向无环图）**。

## 3. 解法一：DFS + 记忆化搜索

这是最直接的实现：计算某个节点时递归计算它的依赖，并把结果缓存起来，避免重复求值。

```js
function calculateAll(input) {
  const nodeMap = new Map(input.map(node => [node.id, node]));
  const cache = new Map();
  const calculating = new Set();

  function calculate(id) {
    if (cache.has(id)) return cache.get(id);

    const node = nodeMap.get(id);
    if (!node) {
      throw new Error(`引用了不存在的节点：${id}`);
    }

    if (calculating.has(id)) {
      throw new Error(`检测到循环依赖：${id}`);
    }

    calculating.add(id);

    let value;

    if (Object.hasOwn(node, 'value')) {
      value = node.value;
    } else {
      if (!Array.isArray(node.refs) || node.refs.length === 0) {
        throw new Error(`节点 ${id} 缺少 refs`);
      }

      const values = node.refs.map(calculate);

      switch (node.operator) {
        case '+':
          value = values.reduce((a, b) => a + b);
          break;
        case '-':
          value = values.reduce((a, b) => a - b);
          break;
        case '*':
          value = values.reduce((a, b) => a * b);
          break;
        case '/':
          value = values.reduce((a, b) => {
            if (b === 0) {
              throw new Error(`节点 ${id} 发生除零错误`);
            }
            return a / b;
          });
          break;
        default:
          throw new Error(`节点 ${id} 使用了未知操作符：${node.operator}`);
      }
    }

    calculating.delete(id);
    cache.set(id, value);
    return value;
  }

  for (const node of input) {
    calculate(node.id);
  }

  // 按原输入顺序输出，方便阅读和测试。
  return Object.fromEntries(
    input.map(node => [node.id, cache.get(node.id)])
  );
}
```

### 输出

```js
{
  A: 265,
  B: 250,
  C: 10,
  D: 5,
  E: 5,
  F: 2
}
```

### 复杂度

设节点数为 `V`，引用关系数为 `E`：

- 时间复杂度：`O(V + E)`
- 空间复杂度：`O(V + E)`，包括节点映射、缓存、递归栈和依赖关系

## 4. 手工计算过程

```text
C = 10
F = 2
E = C / F = 10 / 2 = 5
D = C - E = 10 - 5 = 5
B = C * D * E = 10 * 5 * 5 = 250
A = B + C + D = 250 + 10 + 5 = 265
```

最终结果：

| 节点 | 值 |
|---|---:|
| A | 265 |
| B | 250 |
| C | 10 |
| D | 5 |
| E | 5 |
| F | 2 |

## 5. 为什么它像 LeetCode 题目

这不是某一道 LeetCode 的原题，而是几类经典问题的组合：

### 5.1 LeetCode 2115 — Find All Possible Recipes from Given Supplies

- **相似点**：一个节点只有在所有依赖都可用后才能生成；`C、F` 类似初始 supplies。
- **对应算法**：拓扑排序、入度表、反向依赖表。
- [题目（LeetCode）](https://leetcode.com/problems/find-all-possible-recipes-from-given-supplies/)
- [官方解答与社区解法](https://leetcode.com/problems/find-all-possible-recipes-from-given-supplies/solutions/)

### 5.2 LeetCode 631 — Design Excel Sum Formula

- **相似点**：节点类似 Excel 单元格，一个单元格的值由其他单元格计算得到。
- **区别**：原题重点是公式保存和单元格更新；本题支持多种算术运算和循环检测。
- [题目（LeetCode）](https://leetcode.com/problems/design-excel-sum-formula/)
- [官方解答与社区解法](https://leetcode.com/problems/design-excel-sum-formula/solutions/)

### 5.3 LeetCode 399 — Evaluate Division

- **相似点**：把变量和变量关系建模成图，再通过图搜索求值。
- **区别**：399 主要处理变量之间的比率，本题是一个带多种运算符的表达式 DAG。
- [题目（LeetCode）](https://leetcode.com/problems/evaluate-division/)
- [官方解答与社区解法](https://leetcode.com/problems/evaluate-division/solutions/)

### 5.4 LeetCode 207 / 210 — Course Schedule I & II

- **相似点**：节点之间存在前置依赖，需要判断是否出现环，并生成合法计算顺序。
- **对应算法**：DFS 三色标记或 Kahn 拓扑排序。
- [207. Course Schedule](https://leetcode.com/problems/course-schedule/)
- [207 解答](https://leetcode.com/problems/course-schedule/solutions/)
- [210. Course Schedule II](https://leetcode.com/problems/course-schedule-ii/)
- [210 解答](https://leetcode.com/problems/course-schedule-ii/solutions/)

## 6. 如何选择算法

| 场景 | 推荐方法 |
|---|---|
| 只计算一个或少量目标节点 | DFS + 记忆化搜索 |
| 一次性计算全部节点 | DFS 或拓扑排序 |
| 需要明确的执行顺序 | Kahn 拓扑排序 |
| 需要检测循环依赖 | DFS 三色标记或拓扑排序 |
| 输入值会频繁变化 | 建立反向依赖图，增量重算受影响节点 |
| 需要模拟 Excel 公式系统 | 依赖图 + 缓存失效/增量更新 |

## 7. 注意事项

1. **减法和除法有顺序**：`refs: ['X', 'Y', 'Z']` 按 `((X - Y) - Z)` 或 `((X / Y) / Z)` 计算。
2. **区分值不存在和数值为 0**：不要写 `if (node.value)`，应使用 `Object.hasOwn(node, 'value')`。
3. **必须检测循环依赖**：例如 `A → B → A` 不存在合法计算结果。
4. **处理缺失引用**：`refs` 中出现未定义节点时应立即报错。
5. **处理除零错误**：除数为 `0` 时应提供明确错误信息。
6. **浮点精度**：涉及小数时要考虑 JavaScript 浮点误差；金融场景建议使用定点数或 Decimal 库。

## 8. 总结

这个问题可以归类为：

```text
Graph · DAG · DFS · Memoization · Topological Sort
Expression Evaluation · Cycle Detection
```

结构上最接近 **LeetCode 2115**，求值行为类似 **LeetCode 631**，图搜索思路类似 **LeetCode 399**，循环检测则对应 **LeetCode 207/210**。
