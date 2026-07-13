# 全栈开发工程师面试题库：JS / Vue / 后端

> 日期：2026-07-13  
> 场景：全栈开发工程师岗位，重点考察高质量前端、Vue 工程能力、JavaScript 基础、后端接口/数据库/稳定性能力。  
> 用法：每个问题都包含「标准答案要点」和「深挖追问」。面试时不要只听定义，要让候选人结合真实项目讲取舍、问题定位和复盘。

---

## 一、JavaScript 部分

### 1. 事件循环：宏任务和微任务

**问题：**

下面代码输出顺序是什么？为什么？

```js
console.log('script start')

setTimeout(() => {
  console.log('setTimeout')
}, 0)

Promise.resolve()
  .then(() => {
    console.log('promise1')
  })
  .then(() => {
    console.log('promise2')
  })

console.log('script end')
```

**参考答案：**

输出顺序：

```txt
script start
script end
promise1
promise2
setTimeout
```

原因：

- 整段脚本先作为一个宏任务执行。
- 同步代码立即执行，所以先输出 `script start` 和 `script end`。
- `Promise.then` 回调进入微任务队列。
- `setTimeout` 回调进入宏任务队列。
- 当前宏任务结束后，事件循环会先清空微任务队列，再执行下一个宏任务。
- 所以 Promise 回调早于 setTimeout 执行。

**深挖追问：**

- 宏任务有哪些？微任务有哪些？
- `async/await` 和 Promise 的关系是什么？
- `await` 后面的代码什么时候执行？
- Vue 的 `nextTick` 和事件循环有什么关系？
- 浏览器和 Node.js 的事件循环有什么差异？

---

### 2. async / await 执行顺序

**问题：**

下面代码输出顺序是什么？

```js
async function async1() {
  console.log('async1 start')
  await async2()
  console.log('async1 end')
}

async function async2() {
  console.log('async2')
}

console.log('script start')

setTimeout(() => {
  console.log('setTimeout')
}, 0)

async1()

new Promise(resolve => {
  console.log('promise1')
  resolve()
}).then(() => {
  console.log('promise2')
})

console.log('script end')
```

**参考答案：**

```txt
script start
async1 start
async2
promise1
script end
async1 end
promise2
setTimeout
```

说明：

- `async1()` 调用后立即执行到 `await async2()`。
- `async2()` 内部同步输出 `async2`。
- `await` 后面的 `console.log('async1 end')` 会进入微任务队列。
- 后面的 Promise executor 是同步执行，所以输出 `promise1`。
- 当前同步代码结束后，依次执行微任务：`async1 end`、`promise2`。
- 最后执行宏任务 `setTimeout`。

**深挖追问：**

- `await` 后面如果是普通值会怎样？
- `await` 后面如果 Promise reject，怎么捕获？
- 多个异步请求应该串行还是并行，如何判断？

---

### 3. 闭包与作用域

**问题：**

什么是闭包？下面代码输出什么？

```js
for (var i = 0; i < 3; i++) {
  setTimeout(() => {
    console.log(i)
  }, 1000)
}
```

**参考答案：**

输出：

```txt
3
3
3
```

原因：

- `var` 是函数作用域，不是块级作用域。
- 三个定时器回调共享同一个变量 `i`。
- 循环结束时 `i` 已经变成 3。
- 回调执行时读取到的是同一个 `i` 的最终值。

修复方式：

```js
for (let i = 0; i < 3; i++) {
  setTimeout(() => console.log(i), 1000)
}
```

或者使用立即执行函数：

```js
for (var i = 0; i < 3; i++) {
  ;(function (j) {
    setTimeout(() => console.log(j), 1000)
  })(i)
}
```

**闭包定义：**

闭包是指函数能够访问其词法作用域外层变量，即使外层函数已经执行结束，这些变量仍可能被内部函数引用并保留。

**实际场景：**

- 函数柯里化
- 防抖节流
- 私有变量
- 模块封装
- 异步回调保存上下文

**风险：**

闭包如果长期持有大对象、DOM 节点、定时器引用，可能导致内存无法释放。

**深挖追问：**

- 闭包保存的是变量值还是变量引用？
- 什么情况下闭包会造成内存泄漏？
- Vue 组件中定时器、事件监听、异步回调如何避免泄漏？

---

### 4. this 指向

**问题：**

下面代码输出什么？为什么？

```js
const obj = {
  name: 'A',
  say() {
    console.log(this.name)
  }
}

const fn = obj.say
fn()
```

**参考答案：**

非严格模式下通常输出 `undefined` 或全局对象上的 `name`；严格模式下 `this` 是 `undefined`，访问 `this.name` 会报错。

原因：

- `this` 不是由函数定义位置决定，而是由调用方式决定。
- `obj.say()` 调用时，`this` 指向 `obj`。
- `const fn = obj.say; fn()` 调用时，函数脱离对象，普通函数调用的 `this` 不再指向 `obj`。

修复：

```js
const fn = obj.say.bind(obj)
fn()
```

**箭头函数：**

箭头函数没有自己的 `this`，它会捕获定义时外层作用域的 `this`。

**Vue 场景：**

Vue Options API 的 `methods` 不建议写箭头函数：

```js
export default {
  data() {
    return { count: 1 }
  },
  methods: {
    add: () => {
      this.count++
    }
  }
}
```

这里的 `this` 不会指向 Vue 组件实例，所以无法正确访问 `count`。

**深挖追问：**

- `call`、`apply`、`bind` 的区别是什么？
- 箭头函数适合用在哪里？不适合用在哪里？
- DOM 事件回调里的 `this` 指向谁？

---

### 5. 原型链与 new

**问题：**

JavaScript 的原型链是什么？`new` 一个对象时发生了什么？

**参考答案：**

每个对象都有内部原型，可以通过原型链向上查找属性和方法。函数有 `prototype` 属性，构造函数创建出来的实例，其内部原型会指向构造函数的 `prototype`。

`new` 的过程：

1. 创建一个新对象。
2. 将新对象的原型指向构造函数的 `prototype`。
3. 将构造函数的 `this` 绑定到新对象并执行。
4. 如果构造函数返回对象，则返回该对象；否则返回新创建的对象。

手写 `new`：

```js
function myNew(Constructor, ...args) {
  const obj = Object.create(Constructor.prototype)
  const result = Constructor.apply(obj, args)
  return result !== null && (typeof result === 'object' || typeof result === 'function')
    ? result
    : obj
}
```

**深挖追问：**

- `__proto__` 和 `prototype` 的区别？
- `instanceof` 的原理？
- ES6 class 本质是什么？
- 构造函数返回基本类型和对象分别会怎样？

---

### 6. Promise 并发控制

**问题：**

实现一个并发请求控制器，最多同时执行 `limit` 个任务。

```js
async function limitConcurrency(tasks, limit) {
  // tasks: Array<() => Promise<any>>
}
```

**参考答案：**

```js
async function limitConcurrency(tasks, limit) {
  const results = new Array(tasks.length)
  let index = 0
  let running = 0

  return new Promise((resolve, reject) => {
    function runNext() {
      if (index >= tasks.length && running === 0) {
        resolve(results)
        return
      }

      while (running < limit && index < tasks.length) {
        const current = index++
        running++

        Promise.resolve()
          .then(() => tasks[current]())
          .then(result => {
            results[current] = result
          })
          .catch(reject)
          .finally(() => {
            running--
            runNext()
          })
      }
    }

    runNext()
  })
}
```

**答案要点：**

- 控制同时运行数量。
- 保留结果顺序。
- 任务完成后补充新任务。
- 错误处理策略要明确：遇错立即 reject，还是收集所有结果。

**深挖追问：**

- 如果希望所有任务都执行完，即使某些失败，怎么改？
- `Promise.all` 和这种并发控制有什么区别？
- 大量请求为什么不能直接 `Promise.all`？

---

### 7. 深拷贝

**问题：**

深拷贝和浅拷贝有什么区别？`JSON.parse(JSON.stringify(obj))` 有什么问题？

**参考答案：**

浅拷贝只复制对象第一层属性，嵌套对象仍共享引用。深拷贝会递归复制嵌套结构，避免共享引用。

`JSON.parse(JSON.stringify(obj))` 的问题：

- 会丢失 `undefined`、`function`、`Symbol`。
- `Date` 会变成字符串。
- `RegExp` 会变成空对象。
- 无法处理循环引用。
- `Map`、`Set`、BigInt 等无法正确处理。

处理循环引用可以用 `WeakMap`：

```js
function deepClone(obj, map = new WeakMap()) {
  if (obj === null || typeof obj !== 'object') return obj

  if (map.has(obj)) return map.get(obj)

  if (obj instanceof Date) return new Date(obj)
  if (obj instanceof RegExp) return new RegExp(obj)

  const clone = Array.isArray(obj) ? [] : {}
  map.set(obj, clone)

  Reflect.ownKeys(obj).forEach(key => {
    clone[key] = deepClone(obj[key], map)
  })

  return clone
}
```

**深挖追问：**

- `structuredClone` 了解吗？
- 哪些对象不适合深拷贝？
- 深拷贝在大型前端状态管理中可能带来什么性能问题？

---

### 8. 防抖与节流

**问题：**

防抖和节流的区别是什么？分别适合什么场景？

**参考答案：**

防抖：事件连续触发时，只在停止触发一段时间后执行一次。适合搜索输入、表单校验、窗口 resize 后计算布局。

```js
function debounce(fn, delay) {
  let timer = null
  return function (...args) {
    clearTimeout(timer)
    timer = setTimeout(() => {
      fn.apply(this, args)
    }, delay)
  }
}
```

节流：事件连续触发时，固定时间间隔内最多执行一次。适合滚动监听、拖拽、滚动加载、鼠标移动。

```js
function throttle(fn, delay) {
  let last = 0
  return function (...args) {
    const now = Date.now()
    if (now - last >= delay) {
      last = now
      fn.apply(this, args)
    }
  }
}
```

**深挖追问：**

- 防抖如何支持立即执行？
- 节流如何保证最后一次执行？
- Vue 组件卸载时定时器是否要清理？
- 防抖函数在组件多实例场景下有什么坑？

---

### 9. 模块化与构建

**问题：**

ES Module 和 CommonJS 有什么区别？为什么 Tree Shaking 更依赖 ESM？

**参考答案：**

CommonJS：

- 运行时加载。
- 使用 `require` / `module.exports`。
- 常见于 Node.js。
- 动态性强，静态分析困难。

ES Module：

- 编译时静态分析。
- 使用 `import` / `export`。
- 支持静态依赖图。
- 更利于 Tree Shaking。

Tree Shaking 依赖构建工具在编译阶段判断哪些导出没有被使用。ESM 的静态结构更容易分析，因此更适合做无用代码消除。

**深挖追问：**

- `import()` 动态导入适合什么场景？
- Vite 为什么开发启动快？
- Webpack 和 Vite 的核心差异？
- 前端包体积过大怎么分析和优化？

---

### 10. 浏览器渲染与性能

**问题：**

浏览器从输入 URL 到页面展示发生了什么？

**参考答案要点：**

1. URL 解析。
2. DNS 查询。
3. 建立 TCP 连接。
4. HTTPS 场景下进行 TLS 握手。
5. 发送 HTTP 请求。
6. 服务端返回 HTML。
7. 浏览器解析 HTML 构建 DOM。
8. 解析 CSS 构建 CSSOM。
9. DOM + CSSOM 生成 Render Tree。
10. Layout 计算布局。
11. Paint 绘制。
12. Composite 合成显示。

性能关注：

- 减少阻塞渲染资源。
- 压缩和拆分 JS/CSS。
- 图片懒加载和格式优化。
- 使用 CDN 和缓存。
- 避免频繁回流重绘。
- 动画优先使用 `transform` 和 `opacity`。

**深挖追问：**

- 回流和重绘区别？
- 哪些操作会触发回流？
- LCP、INP、CLS 分别是什么？
- 首屏慢怎么定位？
- 长任务如何排查？

---

## 二、Vue 部分

### 1. Vue 2 / Vue 3 响应式原理

**问题：**

Vue 的响应式原理是什么？Vue 2 和 Vue 3 有什么区别？

**参考答案：**

Vue 2：

- 基于 `Object.defineProperty` 劫持对象属性的 getter/setter。
- getter 中收集依赖，setter 中触发更新。
- 每个响应式属性会关联依赖收集器。
- 缺点是无法天然监听对象新增/删除属性，对数组也需要特殊处理。

Vue 3：

- 基于 `Proxy` 代理整个对象。
- 可以拦截更多操作，如属性读取、设置、删除、`in`、枚举等。
- 响应式系统核心是 `track` 依赖收集和 `trigger` 派发更新。
- 相比 Vue 2，更灵活，对新增属性、数组索引等支持更好。

**深挖追问：**

- Vue 2 为什么需要 `Vue.set`？
- Vue 2 数组响应式有哪些限制？
- Proxy 是否完全没有性能成本？
- `reactive` 包大对象可能有什么问题？
- `track` 和 `trigger` 大概做什么？

---

### 2. ref 和 reactive

**问题：**

Vue 3 里 `ref` 和 `reactive` 怎么选？

**参考答案：**

`ref`：

- 适合基本类型，也可以包对象。
- 访问和修改需要 `.value`。
- 在模板中会自动解包。
- 适合单个值、DOM ref、可替换的状态。

`reactive`：

- 适合对象、数组等复杂结构。
- 返回 Proxy 对象。
- 直接访问属性，不需要 `.value`。
- 不适合直接解构，否则可能丢失响应式。

解构响应式对象时应该使用 `toRef` / `toRefs`：

```js
const state = reactive({ count: 1, name: 'A' })
const { count } = toRefs(state)
```

**深挖追问：**

- `ref({})` 底层会不会变成 reactive？
- `shallowRef` 和 `shallowReactive` 适合什么场景？
- `markRaw` 适合处理什么对象？
- 为什么第三方图表实例不一定要 reactive？

---

### 3. computed、watch、watchEffect

**问题：**

`computed`、`watch`、`watchEffect` 有什么区别？

**参考答案：**

`computed`：

- 用于声明派生状态。
- 有缓存，依赖不变时不会重复计算。
- 应该尽量保持无副作用。

`watch`：

- 用于监听指定数据源变化。
- 适合处理副作用，比如请求接口、写缓存、上报埋点。
- 可以配置 `immediate`、`deep`、`flush`。

`watchEffect`：

- 自动收集回调中使用到的响应式依赖。
- 初始化时会立即执行一次。
- 适合依赖简单、无需明确声明监听源的场景。

**深挖追问：**

- deep watch 为什么可能有性能问题？
- computed 里能不能发请求？为什么不建议？
- `flush: 'pre' | 'post' | 'sync'` 分别有什么区别？
- 如何监听 reactive 对象里的某一个字段？

示例：

```js
watch(
  () => state.user.name,
  (newName, oldName) => {
    console.log(newName, oldName)
  }
)
```

---

### 4. nextTick

**问题：**

Vue 的 `nextTick` 是什么？什么时候用？

**参考答案：**

Vue 修改响应式数据后，不会每次都同步更新 DOM，而是将多次数据变更合并到同一轮更新中，异步刷新 DOM。`nextTick` 用于在 DOM 更新完成后执行回调。

场景：新增列表项后滚动到底部。

```js
items.value.push(newItem)
await nextTick()
containerRef.value.scrollTop = containerRef.value.scrollHeight
```

**深挖追问：**

- Vue 为什么要异步批量更新 DOM？
- 多次修改同一个响应式变量，DOM 会更新几次？
- `nextTick` 和 `setTimeout` 有什么区别？
- `nextTick` 底层和微任务有什么关系？

---

### 5. 组件通信

**问题：**

Vue 组件通信方式有哪些？分别适合什么场景？

**参考答案：**

- `props` / `emit`：父子组件通信。
- `v-model`：父子双向绑定，本质仍是 prop + event。
- `provide` / `inject`：跨层级依赖传递，适合主题、表单上下文、组件库上下文。
- `slot`：父组件向子组件传结构和渲染逻辑。
- `ref` / `defineExpose`：父组件调用子组件暴露的方法。
- Pinia / Vuex：全局共享状态。
- event bus / mitt：非父子通信，但大型项目中要谨慎使用。
- URL query / route params：页面级状态。

**深挖追问：**

- provide/inject 是否响应式？
- 什么时候不应该把状态放全局 store？
- event bus 为什么容易失控？
- 组件库里的 Form / Table 为什么大量使用 provide/inject 和 slot？

---

### 6. v-model 原理

**问题：**

Vue 3 里的 `v-model` 原理是什么？

**参考答案：**

Vue 3 组件上的 `v-model` 默认对应：

- prop：`modelValue`
- event：`update:modelValue`

示例：

```vue
<!-- 父组件 -->
<MyInput v-model="value" />
```

等价于：

```vue
<MyInput
  :model-value="value"
  @update:model-value="value = $event"
/>
```

子组件：

```vue
<script setup>
const props = defineProps({
  modelValue: String
})

const emit = defineEmits(['update:modelValue'])

function onInput(e) {
  emit('update:modelValue', e.target.value)
}
</script>
```

**深挖追问：**

- 多个 v-model 怎么写？
- `defineModel` 了解吗？
- 封装金额输入组件时，内部显示值和外部真实值如何处理？
- 输入中格式化和失焦格式化有什么区别？

---

### 7. 生命周期

**问题：**

Vue 生命周期有哪些？请求、DOM 操作、第三方实例初始化分别放哪里？

**参考答案：**

Options API 常见生命周期：

- `beforeCreate`
- `created`
- `beforeMount`
- `mounted`
- `beforeUpdate`
- `updated`
- `beforeUnmount`
- `unmounted`

Composition API 对应：

- `onMounted`
- `onUpdated`
- `onUnmounted`
- `onActivated`
- `onDeactivated`

实践建议：

- 请求接口：`setup` 或 `onMounted`，取决于是否需要 DOM。
- DOM 操作：`onMounted` 后。
- 第三方图表初始化：`onMounted`。
- 第三方实例销毁：`onUnmounted`。
- KeepAlive 页面激活/失活：`onActivated` / `onDeactivated`。

**深挖追问：**

- 父子组件生命周期顺序？
- KeepAlive 下 mounted/unmounted 还会反复执行吗？
- SSR 下哪些生命周期不会执行？
- WebSocket 在哪里连接和关闭？

---

### 8. Vue 性能优化

**问题：**

Vue 页面卡顿，你怎么定位和优化？

**参考答案：**

定位路径：

1. 确认是接口慢、资源慢、JS 执行慢，还是渲染慢。
2. 使用 Chrome Performance 查看长任务、布局、脚本执行。
3. 使用 Vue Devtools 查看组件更新频率。
4. 检查是否有大列表、深层响应式对象、deep watch、频繁 computed、无意义全局状态更新。

优化方式：

- 大列表使用虚拟列表。
- `v-for` 必须使用稳定唯一 key，避免用 index。
- 合理使用 `v-if` / `v-show`。
- 路由懒加载、组件懒加载。
- 图片懒加载和压缩。
- 避免把超大对象整体 reactive。
- 使用 `shallowRef`、`markRaw` 降低响应式开销。
- 拆分组件，减少不必要的父级状态变更。
- 对高频输入使用防抖。

**深挖追问：**

- key 用 index 有什么问题？
- `v-memo` 是什么？
- 大表格几千行如何优化？
- deep watch 为什么危险？
- 为什么第三方图表实例适合 `markRaw`？

---

### 9. Vue Router 权限设计

**问题：**

管理后台的权限路由怎么设计？

**参考答案：**

整体方案：

1. 登录后获取 token 和用户信息。
2. 后端返回用户角色、菜单权限、按钮权限。
3. 前端根据菜单权限生成动态路由。
4. 使用路由守卫检查登录态和页面权限。
5. 按钮权限通过指令、组件或权限函数控制显示。
6. 后端必须做接口权限校验，前端权限只负责用户体验，不能作为安全边界。

关键点：

- 动态路由刷新丢失：刷新后重新拉取权限并注入路由。
- 403 和 404 区分：无权限是 403，不存在是 404。
- Token 过期：使用刷新 token 或重新登录。
- 多标签页同步：可用 storage event、BroadcastChannel。

**深挖追问：**

- 菜单权限和按钮权限如何建模？
- 路由守卫中如何避免死循环？
- 权限更新后不刷新页面，菜单如何立即变化？
- 前端权限为什么不能防止越权？

---

### 10. Pinia 状态管理

**问题：**

什么时候需要 Pinia？哪些状态应该放 store？

**参考答案：**

适合放 Pinia：

- 用户信息
- 权限菜单
- 全局配置
- 主题语言
- 跨页面共享状态
- 登录态

不适合放 Pinia：

- 单个组件内部临时状态
- 表单输入过程中的局部状态
- 只在一个页面使用的 UI 开关
- 可以通过 URL 表达的筛选条件，除非有跨页面共享需求

Pinia 优势：

- API 简洁。
- TypeScript 支持更好。
- 模块化自然。
- 不再强制 mutation。

**深挖追问：**

- store 如何持久化？
- 刷新页面后 store 丢失怎么办？
- 如何避免 store 变成垃圾桶？
- store 里能不能写异步请求？

---

### 11. 复杂表单设计

**问题：**

一个后台编辑页有 10 个模块、50 个字段、联动校验、动态增删项、草稿保存，你怎么设计？

**参考答案：**

设计思路：

- 按业务模块拆分子组件。
- 父层维护整体表单模型或使用表单上下文。
- 子组件只负责本模块字段展示和局部交互。
- 校验规则按模块拆分，统一汇总。
- 接口 DTO 和前端 Form Model 做转换层，避免页面直接依赖后端结构。
- 动态字段使用 schema 或配置驱动。
- 草稿保存使用防抖 + localStorage / 后端草稿接口。
- 离开页面前检查 dirty 状态，提示未保存。
- 提交前做统一校验和二次确认。

**深挖追问：**

- 表单状态放父组件、Pinia 还是表单库内部？
- 字段联动如何避免 watch 满天飞？
- 如何避免整个页面频繁重渲染？
- 如何测试复杂表单？

---

### 12. 通用 Table 组件设计

**问题：**

设计一个通用 Table 组件，支持自定义列、操作栏、加载态、空状态、分页、筛选。

**参考答案：**

核心设计：

- `columns` 配置列字段、标题、宽度、对齐、是否可排序。
- `data` 传入表格数据。
- `loading` 控制加载状态。
- `pagination` 控制分页。
- 通过具名插槽或作用域插槽支持自定义单元格。
- 通过事件 `change` / `sort-change` / `page-change` 通知父组件。
- 默认行为简单，自定义能力通过 slot 扩展。

示例：

```vue
<BaseTable :columns="columns" :data="list">
  <template #status="{ row }">
    <StatusTag :value="row.status" />
  </template>

  <template #actions="{ row }">
    <button @click="edit(row)">编辑</button>
  </template>
</BaseTable>
```

**深挖追问：**

- slot 内容是在父组件作用域还是子组件作用域编译？
- Table 组件怎么兼顾灵活性和简单性？
- 几千行数据时如何优化？
- 如何做列权限和按钮权限？

---

## 三、后端部分

### 1. RESTful API 设计

**问题：**

如何设计一个用户管理模块的 RESTful API？

**参考答案：**

示例接口：

```txt
GET    /api/users              用户列表
GET    /api/users/:id          用户详情
POST   /api/users              创建用户
PUT    /api/users/:id          整体更新用户
PATCH  /api/users/:id          局部更新用户
DELETE /api/users/:id          删除用户
POST   /api/users/:id/roles    分配角色
```

设计要点：

- URL 使用资源名词，不用动词。
- HTTP Method 表达操作语义。
- 列表接口支持分页、筛选、排序。
- 错误码统一规范。
- 响应结构统一。
- 鉴权和权限校验必须在服务端完成。

示例响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [],
    "total": 0
  }
}
```

**深挖追问：**

- PUT 和 PATCH 区别？
- 分页如何设计？offset 和 cursor 有什么区别？
- REST、GraphQL、BFF 分别适合什么场景？
- 接口版本怎么管理？

---

### 2. 权限系统设计

**问题：**

设计一个管理后台权限系统，包括用户、角色、菜单、按钮、接口权限。

**参考答案：**

常见 RBAC 模型：

- 用户表 `users`
- 角色表 `roles`
- 权限表 `permissions`
- 用户角色关联表 `user_roles`
- 角色权限关联表 `role_permissions`
- 菜单表 `menus`
- 操作日志表 `operation_logs`

权限类型可以分为：

- 菜单权限：控制页面入口。
- 按钮权限：控制页面操作按钮。
- 接口权限：后端真正的安全校验。
- 数据权限：控制能查看哪些组织、部门、数据范围。

关键原则：

- 前端权限只做展示控制，不可作为安全边界。
- 后端必须校验接口权限和数据权限。
- 权限变更后应支持重新加载菜单和权限点。
- 关键操作记录审计日志。

**深挖追问：**

- RBAC 和 ABAC 区别？
- 多租户系统权限怎么设计？
- 数据权限如何落到 SQL 查询？
- 如何防止越权访问？

---

### 3. 数据库表设计：订单/预约系统

**问题：**

设计一个预约演示系统，用户提交预约表单，后台可以查询和处理预约。

**参考答案：**

核心表：

```sql
CREATE TABLE demo_requests (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL,
  phone VARCHAR(32),
  email VARCHAR(128),
  company VARCHAR(128),
  requirement TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  source VARCHAR(64),
  ip VARCHAR(64),
  user_agent VARCHAR(512),
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);
```

常用索引：

```sql
CREATE INDEX idx_demo_requests_created_at ON demo_requests(created_at);
CREATE INDEX idx_demo_requests_status_created ON demo_requests(status, created_at);
CREATE INDEX idx_demo_requests_email ON demo_requests(email);
CREATE INDEX idx_demo_requests_phone ON demo_requests(phone);
```

设计要点：

- 状态字段要可扩展，例如 `pending`、`contacted`、`invalid`、`converted`。
- 后台列表常按时间、状态、手机号/邮箱查询，需要匹配索引。
- 表单提交要防重复、防刷。
- 重要操作记录操作日志。

**深挖追问：**

- 金额字段应该用什么类型？为什么不用 float？
- 状态机如何设计？
- 如何处理重复提交？
- 如何做数据归档？

---

### 4. SQL 优化与慢查询

**问题：**

一个后台列表查询越来越慢，你怎么排查？

**参考答案：**

排查路径：

1. 查看慢查询日志。
2. 用 `EXPLAIN` 分析执行计划。
3. 看是否走索引、扫描行数、排序方式、临时表。
4. 检查 where 条件、order by、limit 是否匹配索引。
5. 检查是否有函数计算、隐式类型转换、前置 `%like` 导致索引失效。
6. 必要时优化 SQL、增加联合索引、拆查询、做冗余字段或归档。

索引原则：

- 高选择性字段更适合作为索引。
- 联合索引遵循最左前缀原则。
- 等值条件通常放前面，范围条件后面的索引列可能无法充分利用。
- 覆盖索引可以减少回表。

**深挖追问：**

- `EXPLAIN` 关注哪些字段？
- 什么是回表？什么是覆盖索引？
- `limit 100000, 20` 为什么慢？怎么优化？
- `like '%keyword%'` 怎么优化？
- 联合索引 `(a, b, c)` 在哪些查询下能生效？

---

### 5. 事务与一致性

**问题：**

订单支付回调如何保证幂等和数据一致性？

**参考答案：**

关键点：

- 支付回调可能重复到达，必须幂等。
- 使用支付流水号或第三方交易号建立唯一索引。
- 在事务中检查当前订单状态。
- 只有订单处于可支付状态时才更新为已支付。
- 记录支付流水。
- 更新订单状态和写支付流水应在同一事务内。

示例逻辑：

```txt
begin transaction
  查询支付流水是否已存在
  如果存在，直接返回成功

  查询订单并加锁
  如果订单已支付，返回成功
  如果金额不一致，记录异常并拒绝

  写支付流水
  更新订单状态为 paid
commit
```

**深挖追问：**

- 什么是幂等？
- 悲观锁和乐观锁怎么选？
- 事务隔离级别有哪些？
- 脏读、不可重复读、幻读是什么？
- 分布式事务如何处理？

---

### 6. Redis 缓存设计

**问题：**

Redis 在业务系统里常用于哪些场景？缓存一致性怎么处理？

**参考答案：**

常见场景：

- 热点数据缓存。
- Session / Token 存储。
- 验证码。
- 分布式锁。
- 排行榜。
- 计数器。
- 限流。

缓存问题：

- 缓存穿透：查询不存在的数据。解决：缓存空值、布隆过滤器。
- 缓存击穿：热点 key 过期，大量请求打到数据库。解决：互斥锁、热点 key 不过期、提前刷新。
- 缓存雪崩：大量 key 同时过期。解决：过期时间加随机值、多级缓存、限流降级。

一致性常见方案：

- 更新数据库后删除缓存。
- 删除失败要有重试机制。
- 对一致性要求高的场景，需要结合消息队列、binlog 订阅或强制读库。

**深挖追问：**

- 先更新数据库还是先删缓存？
- 延迟双删有什么问题？
- Redis 分布式锁如何实现？
- Redlock 有什么争议？
- Redis 内存满了怎么办？

---

### 7. 登录鉴权

**问题：**

JWT 和 Session 有什么区别？后台系统登录态怎么设计？

**参考答案：**

Session：

- 服务端保存会话状态。
- 客户端保存 session id。
- 易于服务端主动失效。
- 分布式部署需要共享 session 或集中存储。

JWT：

- token 自包含用户信息和过期时间。
- 服务端通常无状态校验签名。
- 扩展性好，但主动失效较麻烦。
- 不应放敏感信息。

后台系统常见设计：

- Access Token 短有效期。
- Refresh Token 长有效期。
- Token 过期后无感刷新。
- 服务端维护黑名单或 token version 实现强制下线。
- 所有敏感接口后端鉴权。

**深挖追问：**

- Token 放 localStorage、sessionStorage、Cookie 各有什么风险？
- XSS 和 CSRF 如何防？
- Refresh Token 被盗怎么办？
- 多端登录和踢下线怎么做？

---

### 8. 线上服务变慢排查

**问题：**

用户反馈后台突然变慢，接口从 200ms 变成 5s，你怎么排查？

**参考答案：**

排查路径：

1. 确认影响范围：单用户、单接口、全站、某地区。
2. 查看最近发布：是否刚上线。
3. 查看监控：QPS、响应时间、错误率、CPU、内存、磁盘、网络。
4. 查看应用日志：异常堆栈、慢接口、超时请求。
5. 查看数据库：慢查询、连接数、锁等待、CPU、IO。
6. 查看 Redis：命中率、延迟、连接数、内存。
7. 查看 Nginx / 网关：502、504、上游超时。
8. 临时止血：回滚、扩容、限流、降级、关闭问题功能。
9. 事后复盘：根因分析、补监控、补压测、补预案。

**深挖追问：**

- CPU 高怎么排查？
- 数据库连接池满怎么办？
- Nginx 502 和 504 分别可能是什么原因？
- 如何判断是前端慢还是后端慢？
- 如何写事故复盘？

---

### 9. Docker / CI/CD / 发布

**问题：**

你如何部署一个前后端 Web 系统？

**参考答案：**

基本流程：

- 前端构建静态资源，部署到 Nginx、对象存储或 CDN。
- 后端构建镜像，运行在服务器、Docker Compose 或 Kubernetes。
- 使用环境变量区分 dev/staging/prod。
- CI 流程包括 lint、test、build、镜像构建、推送镜像。
- CD 流程包括部署、健康检查、灰度、回滚。
- 日志、监控、告警要接入。

Dockerfile 优化：

- 使用多阶段构建。
- 减少镜像层和无用依赖。
- 固定基础镜像版本。
- 非 root 用户运行服务。

**深挖追问：**

- 蓝绿发布和灰度发布区别？
- readinessProbe 和 livenessProbe 区别？
- 容器服务挂了如何自动恢复？
- 如何回滚？
- 如何管理配置和密钥？

---

### 10. 日志、监控和可观测性

**问题：**

一个线上系统应该有哪些日志和监控？

**参考答案：**

日志：

- 访问日志。
- 应用日志。
- 错误日志。
- 慢查询日志。
- 操作审计日志。
- 发布日志。

监控指标：

- QPS。
- 响应时间 P50/P90/P99。
- 错误率。
- CPU、内存、磁盘、网络。
- 数据库连接数、慢查询、锁等待。
- Redis 命中率、内存、延迟。
- 队列堆积。

可观测性三件套：

- Logs：日志。
- Metrics：指标。
- Traces：链路追踪。

**深挖追问：**

- 为什么只看平均响应时间不够？
- P99 有什么意义？
- Trace ID 如何贯穿前后端和微服务？
- 告警如何避免太多噪音？

---

### 11. 防刷和限流

**问题：**

官网预约表单如何防止恶意刷提交？

**参考答案：**

可用方案：

- 前端基础校验，但不能只依赖前端。
- 后端按 IP、邮箱、手机号限流。
- Redis 计数器实现滑动窗口或令牌桶。
- 图形验证码、人机验证。
- 黑名单和风控规则。
- 同一邮箱/手机号短时间内限制重复提交。
- 异常流量告警。

简单限流：

```txt
key = rate:demo_request:{ip}
每次请求 incr key
第一次设置过期时间 60s
超过阈值拒绝
```

**深挖追问：**

- 固定窗口、滑动窗口、令牌桶、漏桶区别？
- 分布式环境下限流怎么做？
- 如何避免误伤真实用户？
- 只靠验证码够不够？

---

### 12. BFF / GraphQL / REST 取舍

**问题：**

REST、GraphQL、BFF 分别适合什么场景？

**参考答案：**

REST：

- 简单清晰，资源模型明确。
- 适合大多数 CRUD 和管理后台。

GraphQL：

- 客户端可以声明需要的数据。
- 适合多端、多视图、数据聚合复杂场景。
- 需要处理权限、复杂度限制、缓存等问题。

BFF：

- Backend For Frontend。
- 为特定前端场景聚合和裁剪数据。
- 适合前端需要聚合多个后端接口、不同端数据结构差异大的场景。

**深挖追问：**

- BFF 会不会导致业务逻辑分散？
- GraphQL 如何防止复杂查询拖垮服务？
- 后端接口直接按页面结构返回有什么风险？
- 什么时候没有必要引入 BFF？

---

## 四、综合 Case

### Case 1：SaaS 管理后台「用户管理 + 权限配置」

**问题：**

现在要做一个 SaaS 管理后台的用户管理和权限配置模块，要求支持：

- 用户列表
- 用户新增/编辑/禁用
- 角色分配
- 菜单权限
- 按钮权限
- 动态路由
- 复杂筛选
- 批量操作

你用 Vue + 后端服务怎么设计？

**优秀答案要点：**

前端：

- Vue Router 做动态路由。
- Pinia 存用户信息、权限菜单、按钮权限。
- 用户列表组件拆分为筛选区、表格区、弹窗表单、权限配置组件。
- Table 使用插槽支持状态、操作栏自定义。
- 复杂筛选可以同步到 URL query，方便刷新和分享。
- 批量操作要处理 loading、错误反馈和二次确认。
- 按钮权限用指令或权限组件封装。

后端：

- RBAC 表结构：用户、角色、权限、关联表。
- 菜单权限、按钮权限、接口权限统一建模。
- 后端接口必须校验权限。
- 批量操作要做事务和操作日志。
- 列表查询要设计索引，如状态、创建时间、手机号/邮箱。

稳定性：

- 关键操作写审计日志。
- 接口响应时间和错误率监控。
- 权限变更后支持刷新权限缓存。

**深挖追问：**

- 权限更新后，前端不刷新页面怎么立即生效？
- 动态路由刷新丢失怎么解决？
- 如何防止用户绕过前端直接调用接口？
- 批量禁用用户时，部分失败怎么处理？
- 如何设计操作日志？

---

### Case 2：AI 产品官网 + 预约演示表单

**问题：**

做一个高质感 AI 产品官网，包含首页、产品介绍、客户案例、预约演示表单和后台预约列表，你如何设计？

**优秀答案要点：**

前端：

- 官网可选 SSG/SSR，提高 SEO 和首屏性能。
- 高质感页面关注字体、间距、动效、图片、响应式。
- 动画优先使用 CSS transform/opacity，复杂动画可用 GSAP/Framer Motion。
- 表单做前端校验、防重复提交、loading 和成功反馈。
- 图片用 WebP/AVIF、懒加载、CDN。

后端：

- 提供预约提交 API 和后台查询 API。
- 预约表设计状态、来源、IP、UA、创建时间。
- 防刷：IP 限流、验证码、邮箱/手机号去重。
- 后台列表支持分页、筛选和状态处理。

部署：

- 前端静态资源走 CDN。
- 后端 Docker 部署。
- Nginx 反向代理。
- CI/CD 自动构建发布。
- 日志、告警、表单提交成功率监控。

**深挖追问：**

- 首屏 LCP 怎么优化？
- 表单接口如何防刷？
- 后台列表慢查询怎么优化？
- 如果官网访问量突然增长 10 倍怎么办？
- 如何用 AI 辅助开发但保证质量？

---

## 五、面试评分建议

### 初级水平

通常表现：

- 能写页面、调接口。
- 知道生命周期、路由、状态管理。
- 能背基础概念，但讲不清原理和项目取舍。
- 后端只会简单 CRUD。

### 中级水平

应该具备：

- 能讲清 JS 异步、闭包、this、原型等核心机制。
- 能解释 Vue 响应式、组件通信、性能优化。
- 有复杂表单、权限路由、后台系统经验。
- 能独立设计接口、数据库表和索引。
- 有基本线上问题排查思路。

### 高级水平

应该具备：

- 不只会“怎么做”，还能解释“为什么这样做”。
- 能从业务、用户体验、工程质量、稳定性综合权衡。
- 能设计可维护的前端架构和后端模块。
- 有真实线上事故处理和复盘经验。
- 能把 AI 工具融入需求拆解、编码、测试、Review、文档流程，但不会盲信 AI 生成代码。

---

## 六、最推荐现场问的 10 道题

1. 事件循环代码输出题，解释宏任务和微任务。
2. `this` 指向题，追问 Vue methods 为什么不能用箭头函数。
3. 手写 Promise 并发控制，最多同时 3 个请求。
4. Vue 2 和 Vue 3 响应式原理差异。
5. `ref`、`reactive`、`computed`、`watch`、`watchEffect` 怎么选。
6. Vue 管理后台权限路由、菜单权限、按钮权限如何设计。
7. 复杂表单页面如何拆组件、管状态、做校验和草稿。
8. 设计用户/角色/权限系统的数据库和接口。
9. 后台列表慢查询如何排查和优化索引。
10. 线上接口从 200ms 变成 5s，如何定位和止血。

---

## 七、明显风险信号

- 只会背概念，讲不出真实项目细节。
- 说熟 Vue，但讲不清响应式和组件更新机制。
- 说熟 JS，但事件循环、闭包、this 一追问就乱。
- 说做过后端，但不会设计表、索引、事务和权限。
- 说会 Redis，只知道 set/get。
- 说会部署，但没写过 Dockerfile，没做过回滚。
- 没有线上问题排查思路。
- 说会 AI 编程，但只是“让 ChatGPT 写代码”，没有验证、测试和 Review 流程。
